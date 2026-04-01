"""Simple event recorder — writes events to the database.

No pub/sub, no subscribers. Just persist and query.
The bus layer can be added on top later for real-time streaming.
"""

import logging
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

    with get_session() as session:
        session.add(event)

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
    with get_session() as session:
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


def get_events(
    execution_id: str | None = None,
    event_type: EventType | None = None,
    parent_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Query events with optional filters.

    Args:
        execution_id: Filter by workflow execution ID.
        event_type: Filter by event type.
        parent_id: Filter by parent event ID.
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
