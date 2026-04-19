"""Simple event recorder — writes events to the database.

No pub/sub, no subscribers. Just persist and query.
The bus layer can be added on top later for real-time streaming.
"""

import logging
import time
import uuid
from typing import Any

from sqlmodel import col, select

from temper_ai.database import get_session
from temper_ai.observability.event_types import EventType
from temper_ai.observability.models import Event

logger = logging.getLogger(__name__)


def record(
    event_type: EventType,
    data: dict[str, Any] | None = None,
    parent_id: str | None = None,
    execution_id: str | None = None,
    status: str | None = None,
    event_id: str | None = None,
) -> str:
    """Record an observability event to the database.

    Args:
        event_type: The event type (use EventType enum).
        data: Arbitrary JSON payload — caller defines the shape.
        parent_id: ID of the parent event (for hierarchy).
        execution_id: Top-level workflow execution ID (denormalized for fast queries).
        status: Optional status (running, completed, failed).
        event_id: Optional pre-generated ID. Auto-generated if not provided.

    Returns:
        The event ID.
    """
    eid = event_id or str(uuid.uuid4())

    event = Event(
        id=eid,
        type=event_type,
        parent_id=parent_id,
        execution_id=execution_id,
        status=status,
        data=data or {},
    )

    _db_write_with_retry(lambda s: s.add(event))

    return eid


def update_event(
    event_id: str,
    status: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    """Update an existing event (e.g., mark completed, add output data).

    Args:
        event_id: The event to update.
        status: New status value.
        data: If provided, merges into existing data.
    """
    def _do_update(session):
        event = session.get(Event, event_id)
        if event is None:
            logger.warning("Event %s not found for update", event_id)
            return

        if status is not None:
            event.status = status
        if data is not None:
            merged = {**event.data, **data}
            event.data = merged

        session.add(event)

    _db_write_with_retry(_do_update)


def _db_write_with_retry(fn, max_retries: int = 3, base_delay: float = 0.5) -> None:
    """Execute a DB write with retry on transient failures."""
    for attempt in range(max_retries):
        try:
            with get_session() as session:
                fn(session)
            return
        except Exception:
            if attempt == max_retries - 1:
                logger.error("DB write failed after %d attempts", max_retries, exc_info=True)
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning("DB write failed (attempt %d/%d), retrying in %.1fs", attempt + 1, max_retries, delay)
            time.sleep(delay)


def copy_events_for_fork(
    source_execution_id: str,
    new_execution_id: str,
    restored_node_names: set[str],
) -> str | None:
    """Copy events from a source execution into a new execution for fork/re-run.

    Copies the workflow_started event and all descendant events belonging to
    restored nodes (stages, agents, LLM calls, tool calls — the full tree).
    Remaps execution_id to the new one and generates new event IDs while
    preserving the parent-child hierarchy.

    Returns the new workflow_started event ID (so the executor can parent new events to it).
    """
    # Load source events into plain dicts (detached from session)
    with get_session() as session:
        stmt = (
            select(Event)
            .where(Event.execution_id == source_execution_id)
            .order_by(col(Event.timestamp))
            .limit(10000)
        )
        source_events = [
            {
                "id": e.id,
                "type": e.type,
                "parent_id": e.parent_id,
                "status": e.status,
                "data": dict(e.data) if e.data else {},
                "timestamp": e.timestamp,
            }
            for e in session.exec(stmt).all()
        ]

    if not source_events:
        return None

    # Build parent→children index and find the workflow_started event
    children_of: dict[str, list[dict]] = {}
    workflow_event: dict | None = None

    for e in source_events:
        if e["type"] == "workflow.started":
            workflow_event = e
        parent_id = e["parent_id"]
        if parent_id and isinstance(parent_id, str):
            children_of.setdefault(parent_id, []).append(e)

    if not workflow_event:
        return None

    # Find stage events that belong to restored nodes
    stage_events_to_copy: list[dict] = []
    for child in children_of.get(workflow_event["id"], []):
        node_name = child["data"].get("name", "")
        if node_name in restored_node_names:
            stage_events_to_copy.append(child)

    # BFS: collect all descendant events of the stage events to copy
    id_remap: dict[str, str] = {}
    events_to_copy: list[dict] = []

    # Include the workflow_started event
    new_wf_id = str(uuid.uuid4())
    id_remap[workflow_event["id"]] = new_wf_id
    events_to_copy.append(workflow_event)

    # Collect stage events and all their descendants
    queue = list(stage_events_to_copy)
    while queue:
        event = queue.pop(0)
        if event["id"] not in id_remap:
            id_remap[event["id"]] = str(uuid.uuid4())
            events_to_copy.append(event)
        for child in children_of.get(event["id"], []):
            if child["id"] not in id_remap:
                queue.append(child)

    # Write copies with remapped IDs
    def _write_copies(session):
        for e in events_to_copy:
            new_id = id_remap[e["id"]]
            new_parent = id_remap.get(e["parent_id"]) if e["parent_id"] else None
            data = dict(e["data"])
            if e["id"] != workflow_event["id"]:
                data["restored_from_fork"] = True
                data["source_execution_id"] = source_execution_id

            copy = Event(
                id=new_id,
                type=e["type"],
                parent_id=new_parent,
                execution_id=new_execution_id,
                status=e["status"],
                data=data,
                timestamp=e["timestamp"],
            )
            session.add(copy)

    _db_write_with_retry(_write_copies)

    logger.info(
        "Copied %d events from execution '%s' to '%s' for %d restored nodes",
        len(events_to_copy), source_execution_id, new_execution_id, len(restored_node_names),
    )
    return new_wf_id


def get_events(
    execution_id: str | None = None,
    event_type: EventType | None = None,
    parent_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Query events with optional filters.

    Args:
        execution_id: Filter by workflow execution ID.
        event_type: Filter by event type.
        parent_id: Filter by parent event ID.
        status: Filter by event status.
        limit: Max results.

    Returns:
        List of event dicts ordered by timestamp.
    """
    with get_session() as session:
        stmt = select(Event)

        if execution_id is not None:
            stmt = stmt.where(Event.execution_id == execution_id)
        if event_type is not None:
            stmt = stmt.where(Event.type == event_type)
        if parent_id is not None:
            stmt = stmt.where(Event.parent_id == parent_id)
        if status is not None:
            stmt = stmt.where(Event.status == status)

        stmt = stmt.order_by(col(Event.timestamp)).limit(limit)
        results = session.exec(stmt).all()
        return [
            {
                "id": e.id,
                "type": e.type,
                "parent_id": e.parent_id,
                "execution_id": e.execution_id,
                "status": e.status,
                "data": e.data,
                "timestamp": e.timestamp.isoformat(),
            }
            for e in results
        ]
