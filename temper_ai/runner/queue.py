"""Hand a run to the worker, which starts it in its own box (external mode).

The API's Start, Resume, Fork and clean-up passes use it, and so does the worker's reaper when
it carries a parked Pi run on after the owner's answer (runner/parked.py), so a run is put in
the queue the same way whoever puts it there.
"""

from __future__ import annotations


class AlreadyQueued(Exception):  # noqa: N818 - a refusal, said as a fact
    """The run already has a box, or is about to: it never gets a second one."""

    def __init__(self, execution_id: str, status: str):
        super().__init__(f"Execution '{execution_id}' is already {status}")
        self.execution_id = execution_id
        self.status = status


def queue_run(
    execution_id: str,
    workflow_name: str,
    workspace_path: str | None,
    inputs: dict | None,
    start: str | None = None,
    extra: dict | None = None,
) -> None:
    """Queue a run for the worker, which starts it in its own box.

    ``start`` is how the box begins: a fresh run (None), or ``resume`` /
    ``fork`` from the run's checkpoints, or ``cleanup`` to run only the
    clean-ups a failed run was holding (read by ``temper run-workflow``).
    ``extra`` is anything else the box needs to know: the steps someone ticked
    to run again (``rerun``), or the only paths a pass may run (``only``).
    A resumed run keeps its row: a finished one goes back to queued. One
    that is still queued or running is refused (AlreadyQueued), so a run never
    has two boxes.
    """
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    metadata: dict = {"start": start} if start else {}
    # Only the worker writes a run's box profile record (spawner/box_profile.py): whatever
    # asks for a run can't hand one in.
    metadata.update({k: v for k, v in (extra or {}).items() if v and k != "box_profile"})
    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
        ).first()
        if row is None:
            session.add(WorkflowRun(
                execution_id=execution_id,
                workflow_name=workflow_name,
                workspace_path=workspace_path or "",
                inputs=inputs or {},
                status="queued",
                spawner_metadata=metadata,
            ))
            return
        if row.status in ("queued", "running"):
            raise AlreadyQueued(execution_id, row.status)
        row.workflow_name = workflow_name
        row.workspace_path = workspace_path or ""
        row.inputs = inputs or {}
        row.status = "queued"
        row.spawner_kind = None
        row.spawner_handle = None
        # The run's box profile record stays: its generation and history (was it ever
        # sealed?) decide what the next box may be (spawner/box_profile.py).
        kept = (row.spawner_metadata or {}).get("box_profile")
        row.spawner_metadata = metadata if kept is None else {**metadata, "box_profile": kept}
        row.cancel_requested = False
        row.started_at = None
        row.completed_at = None
        row.result = None
        row.error = None
        session.add(row)
