"""The event inbox, looked at from outside (``temper events``).

    GET  /api/events                 newest first; ?source= &status= &since= &subject= &limit=
    GET  /api/events/{id}            one event, with its payload and result
    POST /api/events/{id}/replay     handle it again (refused when that would start a run twice)

Every event temper receives from Linear, Notion, Slack and Telegram is kept
here before it is handled (temper_ai/integrations/inbox). Behind the API
token like the rest of /api. No keys are kept in an event: Slack's old
verification token is dropped before saving.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from temper_ai.integrations.inbox import service, store

router = APIRouter(prefix="/api/events", tags=["events"])


def _sweeper() -> dict[str, Any]:
    sw = service.sweeper()
    if sw is None:
        return {"running": False}
    return {"running": sw.running, "last_sweep_at": sw.last_sweep_at, "last_error": sw.last_error,
            "counts": dict(sw.counts)}


@router.get("")
def list_events(source: str | None = None, status: str | None = None, since: str | None = None,
                subject: str | None = None, limit: int = 50) -> dict[str, Any]:
    if status and status not in store.STATUSES:
        raise HTTPException(400, f"status is one of: {', '.join(store.STATUSES)}")
    try:
        since_at = store.parse_since(since)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    rows = store.listing(source=source or None, status=status or None, since=since_at, subject=subject or None,
                         limit=limit)
    return {"events": [r.brief() for r in rows], "sources": service.sources(), "sweeper": _sweeper()}


@router.get("/{event_id}")
def show_event(event_id: int) -> dict[str, Any]:
    row = store.get(event_id)
    if row is None:
        raise HTTPException(404, f"there is no event {event_id}")
    return row.full()


@router.post("/{event_id}/replay")
def replay_event(event_id: int) -> Any:
    if store.get(event_id) is None:
        raise HTTPException(404, f"there is no event {event_id}")
    ok, why = service.replay(event_id)
    if not ok:
        return JSONResponse(status_code=409, content={"replayed": False, "reason": why})
    return {"replayed": True, "message": why}
