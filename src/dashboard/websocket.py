"""WebSocket handler for real-time dashboard updates."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

EVENT_QUEUE_MAXSIZE = 256
HEARTBEAT_TIMEOUT_SECONDS = 30.0


def create_ws_endpoint(data_service: Any) -> Callable:
    """Create WebSocket endpoint handler.

    Returns an async callable suitable for ``app.add_api_websocket_route``.
    """

    async def websocket_handler(websocket: WebSocket, workflow_id: str) -> None:
        """Handle WebSocket connection for real-time workflow updates."""
        await websocket.accept()

        subscription_id = None
        event_queue: asyncio.Queue = asyncio.Queue(maxsize=EVENT_QUEUE_MAXSIZE)

        def on_event(event: Any) -> None:
            """Callback from event bus (runs in sync emitting thread)."""
            event_dict = {
                "type": "event",
                "event_type": event.event_type,
                "timestamp": event.timestamp.isoformat(),
                "data": event.data,
                "workflow_id": event.workflow_id,
                "stage_id": event.stage_id,
                "agent_id": event.agent_id,
            }
            try:
                event_queue.put_nowait(event_dict)
            except asyncio.QueueFull:
                logger.warning("Event queue full, dropping event")

        try:
            # Send initial snapshot
            snapshot = data_service.get_workflow_snapshot(workflow_id)
            if snapshot:
                await websocket.send_json({"type": "snapshot", "workflow": snapshot})

            # Subscribe to events for this workflow
            subscription_id = data_service.subscribe_workflow(workflow_id, on_event)

            # Stream events with heartbeat
            while True:
                try:
                    event_dict = await asyncio.wait_for(
                        event_queue.get(), timeout=HEARTBEAT_TIMEOUT_SECONDS
                    )
                    await websocket.send_json(event_dict)
                except asyncio.TimeoutError:
                    await websocket.send_json(
                        {
                            "type": "heartbeat",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
        except WebSocketDisconnect:
            logger.debug("WebSocket disconnected for workflow %s", workflow_id)
        except Exception:
            logger.warning("WebSocket error", exc_info=True)
        finally:
            if subscription_id:
                data_service.unsubscribe(subscription_id)

    return websocket_handler
