"""End a held clean-ups wait and queue the work that follows it, in one commit.

Two callers end a wait this way: a cleanup pass releasing it (Give up, the deadline), and a
fork taking it over. Either both writes land or neither does.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from temper_ai.database import get_session
from temper_ai.runner import holds, queue

if TYPE_CHECKING:
    from sqlmodel import Session

logger = logging.getLogger(__name__)


class HoldNoLongerWaiting(Exception):
    """A fork's source was holding its clean-ups when the fork began, but Give up or the
    deadline ended that wait since: its clean-ups are queued for the same workspace."""

    def __init__(self, execution_id: str):
        super().__init__(f"Run '{execution_id}' stopped holding its clean-ups while the fork "
                         "was being prepared; they now run in its workspace")
        self.execution_id = execution_id


def _end_hold_then_queue(execution_id: str, status: str, by: str,
                         queue_work: Callable[[Session, dict | None], None]) -> dict | None:
    """End a still-waiting hold, then queue work, in the same transaction (hold first).

    Lock order is hold then run row. Both ordinary and parked resumes commit their queue
    transaction before taking a hold, so they hold no run-row lock while asking for this
    hold. Anything ``queue_work`` raises (an unsafe workspace, a busy row, a refusal) rolls
    the hold's end back too. Returns the ended hold, or None when it was not waiting.
    """
    with get_session() as session:
        ended = holds.end_in(session, execution_id, status, by)
        queue_work(session, ended)
    return ended


def queue_held_cleanups(execution_id: str, *, by: str,
                        refuse_held: Callable[[dict], None] | None = None) -> dict | None:
    """Return the released hold, or None when another actor already ended it.

    ``refuse_held`` sees the ended hold inside the transaction, before anything is queued;
    whatever it raises refuses the release too, so the wait and its deadline stay as they
    were. The deadline and original cleanup paths remain retryable.
    """
    paths: list[str] = []

    def queue_cleanup_pass(session: Session, ended: dict | None) -> None:
        if ended is None:
            return
        if refuse_held is not None:
            refuse_held(ended)
        paths.extend(str(c["path"]) for c in ended["cleanups"] if c.get("path"))
        if paths:
            queue.queue_run_in(session, execution_id, ended["workflow_name"],
                               ended.get("workspace_path") or None, ended.get("inputs") or {},
                               start="cleanup", extra={"only": paths})

    ended = _end_hold_then_queue(execution_id, "released", by, queue_cleanup_pass)
    if ended is not None:
        logger.info("%s: released its held clean-ups with admitted work (by %s, paths=%s)",
                    execution_id, by, paths)
    return ended


def queue_fork_taking_over(source_execution_id: str, fork_execution_id: str,
                           workflow_name: str, workspace_path: str | None, inputs: dict | None,
                           *, lane: Any, source_was_holding: bool) -> dict | None:
    """Queue a fork and take its source's held clean-ups over in one commit, hold first.

    A fork is a new execution id, so the busy-row refusal that guards a same-id successor
    never guards it: if the takeover and the queue were separate commits, a failed takeover
    or a wait ended in between would run the source's clean-ups under the fork. Returns the
    hold taken over, or None when the source holds nothing (the fork is queued as before).
    ``source_was_holding``: the source was holding when the fork began; if that wait has
    ended since, raises HoldNoLongerWaiting and queues nothing.
    """
    def queue_fork(session: Session, taken: dict | None) -> None:
        if taken is None and source_was_holding:
            raise HoldNoLongerWaiting(source_execution_id)
        queue.queue_run_in(session, fork_execution_id, workflow_name, workspace_path, inputs,
                           start="fork", lane=lane)

    taken = _end_hold_then_queue(source_execution_id, "taken_over", fork_execution_id, queue_fork)
    if taken is not None:
        logger.info("%s: fork %s took its held clean-ups over", source_execution_id,
                    fork_execution_id)
    return taken
