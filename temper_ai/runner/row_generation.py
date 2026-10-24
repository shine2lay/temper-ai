"""A run row's generation, and the end write that lands only on that generation.

The reaper and the cancel judge a run row from one read, then end it. Between the read
and the write the run can move on: a resume puts it back in the queue, a new box starts it
(the start raises ``attempts`` in the same commit as ``running``), a new dispatch stamps a
new container on it. An end written by primary key would then end the newer run, or
rewrite one that had already ended.

So the read is kept as a :class:`RowGeneration` (status and attempts, plus who the
dispatch is while the row is queued), and :func:`end_row_if_same_generation` is the end
write fenced on it: one conditional UPDATE that changes the row only while it is still
that generation, and says whether it did.

Who a queued dispatch is, per spawner kind:

* ``docker``: the box's name (``spawner_handle``, the same for every dispatch of one run)
  and this dispatch's container (``spawner_metadata["container_id"]``).
* ``subprocess``: the pid (``spawner_handle``). A later dispatch that gets the same pid
  compares equal: a known residual (pid reuse), not closed here.
* any other kind names no dispatch identity, so a queued row of that kind is never ended
  through the fence; it warns instead.

An identity the judging read didn't have is never taken as equal: the fence writes nothing
that time and warns, with metadata only (the run, the kind, which field is missing).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import update as sa_update
from sqlmodel import Session, col

from temper_ai.runner.models import WorkflowRun
from temper_ai.shared.clock import utcnow
from temper_ai.worker_proto.spawn import SpawnerKind

logger = logging.getLogger(__name__)

QUEUED = "queued"

#: This dispatch's container, as stored on the row: a JSON element (Postgres ``->>``,
#: SQLite ``json_extract``). Missing on the row, it is SQL NULL, and NULL equals nothing.
_ROW_CONTAINER_ID = col(WorkflowRun.spawner_metadata)["container_id"].as_string()


@dataclass(frozen=True)
class RowGeneration:
    """A run row as one read judged it: what an end write must still find there."""

    status: str
    attempts: int
    spawner_kind: str | None
    handle: str | None
    container_id: str | None

    @classmethod
    def from_snapshot(cls, row: Mapping[str, Any]) -> RowGeneration:
        """The generation in one read of the row: the reaper's snapshot, or a row read in the
        caller's own transaction. Never from a later, fresh read: that would judge one
        generation and fence on another.

        Keys: ``status`` and ``attempts`` (required; a missing or ill-typed one raises
        ValueError rather than default to something that could match), and
        ``spawner_kind``, ``spawner_handle`` and ``container_id``. An identity that is
        absent, empty or not a string is kept as None, which a queued fence refuses.
        """
        status = row.get("status")
        if not isinstance(status, str) or not status:
            raise ValueError("a row generation needs the status its read found")
        attempts = row.get("attempts")
        if not isinstance(attempts, int) or isinstance(attempts, bool):
            raise ValueError("a row generation needs the attempts its read found")
        return cls(
            status=status,
            attempts=attempts,
            spawner_kind=_identity(row.get("spawner_kind")),
            handle=_identity(row.get("spawner_handle")),
            container_id=_identity(row.get("container_id")),
        )


def end_row_if_same_generation(
    session: Session,
    execution_id: str,
    judged: RowGeneration,
    *,
    status: str,
    keep_open: bool = False,
    error: dict | None = None,
) -> bool:
    """End the run's row only while it is still the ``judged`` generation.

    One UPDATE of ``status``, ``completed_at`` (unless ``keep_open``: the run is not over)
    and ``error`` (when given), where the row still has the judged status and attempts and,
    for a queued judged row, the judged dispatch (module docstring). True only when exactly
    one row changed. False covers every row this call left alone: another generation, one
    the same generation already ended, no such row, or a queued dispatch the judging read
    can't name (no write then, and a warning). A caller that must tell "already ended" from
    "another generation" reads the row in its own transaction; True never means either.

    Doesn't commit: the caller's session does, with whatever else it decides.
    """
    fence = [
        col(WorkflowRun.execution_id) == execution_id,
        col(WorkflowRun.status) == judged.status,
        col(WorkflowRun.attempts) == judged.attempts,
    ]
    if judged.status == QUEUED:
        dispatch = _queued_dispatch(execution_id, judged)
        if dispatch is None:
            return False
        fence.extend(dispatch)
    values: dict[str, Any] = {"status": status}
    if not keep_open:
        values["completed_at"] = utcnow()
    if error is not None:
        values["error"] = error
    result = session.exec(  # type: ignore[call-overload]
        sa_update(WorkflowRun)
        .where(*fence)
        .values(**values)
        .execution_options(synchronize_session=False),
    )
    return result.rowcount == 1


def _queued_dispatch(execution_id: str, judged: RowGeneration) -> list[Any] | None:
    """The WHERE terms naming the judged dispatch of a queued row; None (and a warning)
    when the judging read can't name it, so nothing is written."""
    kind = judged.spawner_kind
    # A missing identity is refused here, never compared: SQLAlchemy writes ``== None`` as
    # IS NULL, which would match a row that has none either.
    if kind == SpawnerKind.docker.value:
        missing = [name for name, value in (("handle", judged.handle),
                                            ("container_id", judged.container_id)) if not value]
        if missing:
            _no_end(execution_id, kind, missing)
            return None
        return [
            col(WorkflowRun.spawner_handle) == judged.handle,
            _ROW_CONTAINER_ID == judged.container_id,
        ]
    if kind == SpawnerKind.subprocess.value:
        if not judged.handle:
            _no_end(execution_id, kind, ["handle"])
            return None
        # The pid. A later dispatch on the same pid compares equal: pid reuse is a known
        # residual of the subprocess spawner, which carries no per-dispatch token.
        return [col(WorkflowRun.spawner_handle) == judged.handle]
    _no_end(execution_id, kind, [])
    return None


def _no_end(execution_id: str, kind: str | None, missing: list[str]) -> None:
    """Say why a queued row was left alone. Metadata only: never the identities' values."""
    if missing:
        logger.warning(
            "Run %s: the read that judged its queued %s dispatch has no %s; "
            "its row is left alone this time", execution_id, kind, " or ".join(missing))
    else:
        logger.warning(
            "Run %s: spawner kind %r names no dispatch identity, so its queued row "
            "is never ended by the generation fence", execution_id, kind)


def _identity(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
