"""Event API endpoints for the persistent event bus.

Provides endpoints for listing events, subscribing, and replaying events.
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from temper_ai.auth.api_key_auth import require_auth, require_role

logger = logging.getLogger(__name__)


# ── Request / Response models ─────────────────────────────────────────


class SubscribeRequest(BaseModel):
    """POST /api/events/subscribe request body."""

    event_type: str
    agent_id: str | None = None
    handler_ref: str | None = None
    workflow_to_trigger: str | None = None
    source_workflow_filter: str | None = None
    payload_filter: dict[str, Any] | None = None


class ReplayRequest(BaseModel):
    """POST /api/events/replay request body."""

    workflow_id: str
    event_type: str | None = None
    since: datetime | None = None
    limit: int = 100


# ── Router factory ────────────────────────────────────────────────────


def _handle_list_events(
    event_type: str | None, limit: int, offset: int
) -> dict[str, Any]:
    """List recent events from the event store."""
    try:
        from temper_ai.events.event_bus import TemperEventBus

        bus = TemperEventBus(persist=True)
        events = bus.replay_events(event_type=event_type, limit=limit)
        # Apply offset manually since replay_events doesn't support it
        events = list(events)[offset:]
        return {"events": events, "total": len(events)}
    except Exception as e:
        logger.warning("Failed to list events: %s", e)
        return {"events": [], "total": 0}


def _handle_subscribe(body: SubscribeRequest) -> dict[str, Any]:
    """Register a persistent subscription to an event type."""
    from temper_ai.events.event_bus import TemperEventBus

    bus = TemperEventBus(persist=False)
    try:
        subscription_id = bus.subscribe_persistent(
            agent_id=body.agent_id,
            event_type=body.event_type,
            handler_ref=body.handler_ref,
            workflow_to_trigger=body.workflow_to_trigger,
            source_workflow_filter=body.source_workflow_filter,
            payload_filter=body.payload_filter,
        )
        return {
            "subscription_id": subscription_id,
            "event_type": body.event_type,
            "status": "subscribed",
        }
    except Exception as e:
        logger.exception("Failed to subscribe to event type %s", body.event_type)
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register subscription",
        ) from e


def _handle_replay(body: ReplayRequest) -> dict[str, Any]:
    """Replay past events for a workflow."""
    from temper_ai.events.event_bus import TemperEventBus

    bus = TemperEventBus(persist=False)
    try:
        events = bus.replay_events(
            event_type=body.event_type, since=body.since, limit=body.limit
        )
        serializable = [
            e.model_dump() if hasattr(e, "model_dump") else dict(e) for e in events
        ]
        return {
            "events": serializable,
            "total": len(serializable),
            "workflow_id": body.workflow_id,
        }
    except Exception as e:
        logger.exception("Failed to replay events for workflow %s", body.workflow_id)
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to replay events"
        ) from e


def create_event_router(auth_enabled: bool = False) -> APIRouter:
    """Create the events API router."""
    router = APIRouter(prefix="/api/events")
    read_deps = [Depends(require_auth)] if auth_enabled else []
    write_deps = [Depends(require_role("owner", "editor"))] if auth_enabled else []

    @router.get("", dependencies=read_deps)
    def list_events(
        event_type: str | None = Query(None, description="Filter by event type"),
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        """List events with optional filters."""
        return _handle_list_events(event_type, limit, offset)

    @router.post("/subscribe", dependencies=write_deps)
    def subscribe_to_events(body: SubscribeRequest = Body(...)) -> dict[str, Any]:
        """Create a new event subscription."""
        return _handle_subscribe(body)

    @router.post("/replay", dependencies=read_deps)
    def replay_events(body: ReplayRequest = Body(...)) -> dict[str, Any]:
        """Replay events matching a filter."""
        return _handle_replay(body)

    return router
