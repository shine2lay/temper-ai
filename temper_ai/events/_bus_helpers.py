"""Free helper functions for the TemperEventBus."""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlmodel import select

from temper_ai.events._subscription_helpers import matches_filter
from temper_ai.shared.utils.datetime_utils import utcnow

logger = logging.getLogger(__name__)


def persist_event(
    session: Any,
    event_type: str,
    payload: dict[str, Any] | None,
    source_workflow_id: str | None,
    source_stage_name: str | None,
    agent_id: str | None,
) -> str:
    """Create and persist an EventLog record, returning the new event ID.

    Args:
        session: SQLModel/SQLAlchemy session.
        event_type: Type of event.
        payload: Optional event payload.
        source_workflow_id: Originating workflow ID.
        source_stage_name: Originating stage name.
        agent_id: Originating agent ID.

    Returns:
        The generated event ID string.
    """
    from temper_ai.events.models import EventLog

    event_id = str(uuid.uuid4())
    record = EventLog(
        id=event_id,
        event_type=event_type,
        timestamp=utcnow(),
        source_workflow_id=source_workflow_id,
        source_stage_name=source_stage_name,
        agent_id=agent_id,
        payload=payload,
    )
    session.add(record)
    return event_id


def evaluate_subscriptions(
    session: Any,
    event_type: str,
    payload: dict[str, Any] | None,
    source_workflow_id: str | None,
) -> list[Any]:
    """Find active subscriptions matching the given event.

    Args:
        session: SQLModel/SQLAlchemy session.
        event_type: Event type to match.
        payload: Event payload for filter evaluation.
        source_workflow_id: Source workflow for filter evaluation.

    Returns:
        List of matching EventSubscription records.
    """
    from temper_ai.events.models import EventSubscription

    stmt = select(EventSubscription).where(
        EventSubscription.active == True  # noqa: E712
    )
    active_subs = session.exec(stmt).all()

    return [
        sub
        for sub in active_subs
        if matches_filter(sub, event_type, payload, source_workflow_id)
    ]


def convert_to_observability_event(
    event_type: str,
    payload: dict[str, Any] | None,
    source_workflow_id: str | None,
    agent_id: str | None,
) -> Any:
    """Build an ObservabilityEvent from event bus data.

    Args:
        event_type: The event type string.
        payload: Optional payload dict.
        source_workflow_id: Originating workflow ID.
        agent_id: Originating agent ID.

    Returns:
        ObservabilityEvent instance.
    """
    from temper_ai.observability.event_bus import ObservabilityEvent

    data: dict[str, Any] = payload or {}
    return ObservabilityEvent(
        event_type=event_type,
        timestamp=datetime.now(),
        data=data,
        workflow_id=source_workflow_id,
        agent_id=agent_id,
    )
