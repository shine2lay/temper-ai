"""WebSocket handler for real-time dashboard updates."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

EVENT_QUEUE_MAXSIZE = 1024
HEARTBEAT_TIMEOUT_SECONDS = 30.0
CHUNK_IDLE_TIMEOUT_SECONDS = 0.03  # 30ms adaptive idle timeout
CHUNK_BATCH_SIZE = 10  # Flush immediately when buffer reaches this size
DB_POLL_INTERVAL_SECONDS = 2.0  # DB polling interval for cross-process updates
TERMINAL_STATUSES = frozenset({"completed", "failed", "halted", "timeout"})


def _create_event_callback(
    workflow_id: str,
    event_queue: asyncio.Queue,
    chunk_buffer: List[dict],
) -> Callable:
    """Create event callback for event bus subscription.

    Args:
        workflow_id: Workflow ID for logging.
        event_queue: Queue to put non-chunk events.
        chunk_buffer: Buffer for batched stream chunks.

    Returns:
        Event callback function.
    """
    def on_event(event: Any) -> None:
        """Callback from event bus (runs in sync emitting thread)."""
        logger.info("[WebSocket] Received event: %s for workflow %s", event.event_type, workflow_id)
        event_dict = {
            "type": "event",
            "event_type": event.event_type,
            "timestamp": event.timestamp.isoformat(),
            "data": event.data,
            "workflow_id": event.workflow_id,
            "stage_id": event.stage_id,
            "agent_id": event.agent_id,
        }
        # Batch streaming chunks instead of queueing individually
        if event.event_type == "llm_stream_chunk":
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(chunk_buffer.append, event_dict)
            except RuntimeError:
                logger.debug(
                    "No running event loop; dropping stream chunk for workflow %s",
                    workflow_id,
                )
            return

        try:
            event_queue.put_nowait(event_dict)
        except asyncio.QueueFull:
            logger.warning("Event queue full, dropping event")

    return on_event


async def _flush_chunks_task(
    websocket: WebSocket,
    chunk_buffer: List[dict],
    chunk_lock: asyncio.Lock,
) -> None:
    """Flush accumulated stream chunks with adaptive batching.

    Uses a short 30ms idle poll instead of a fixed 100ms interval.
    When the buffer has fewer than CHUNK_BATCH_SIZE items, waits one
    additional interval to allow the producer to batch more chunks.
    When the buffer reaches CHUNK_BATCH_SIZE, flushes immediately.

    Net effect: first token reaches frontend in ~30-60ms instead of
    ~100ms; burst throughput is unchanged.

    Args:
        websocket: WebSocket connection.
        chunk_buffer: Buffer of stream chunks.
        chunk_lock: Lock for buffer access.
    """
    while True:
        await asyncio.sleep(CHUNK_IDLE_TIMEOUT_SECONDS)  # 30ms poll
        if not chunk_buffer:
            continue
        # Pre-lock length check is safe: chunk_buffer.append() is scheduled
        # via call_soon_threadsafe and executes on this same event loop
        # thread, so there is no concurrent mutation.
        if len(chunk_buffer) < CHUNK_BATCH_SIZE:
            await asyncio.sleep(CHUNK_IDLE_TIMEOUT_SECONDS)  # intentional wait for batching
        async with chunk_lock:
            if not chunk_buffer:
                continue
            batch = list(chunk_buffer)
            chunk_buffer.clear()
        try:
            await websocket.send_json({
                "type": "event",
                "event_type": "llm_stream_batch",
                "data": {"chunks": [c["data"] for c in batch]},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except (ConnectionError, OSError, RuntimeError):
            break  # Connection closed


async def _stream_events_loop(
    websocket: WebSocket,
    event_queue: asyncio.Queue,
) -> None:
    """Stream events with heartbeat.

    Args:
        websocket: WebSocket connection.
        event_queue: Queue of events to send.
    """
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


def _workflow_fingerprint(snapshot: Dict[str, Any]) -> str:
    """Create a fingerprint to detect workflow state changes.

    Covers all major UI-visible transitions: workflow status, stage
    statuses, and agent statuses.
    """
    parts = [snapshot.get("status", ""), snapshot.get("end_time", "")]
    for stage in snapshot.get("stages", []):
        parts.append(stage.get("status", ""))
        for agent in stage.get("agents", []):
            parts.append(agent.get("status", ""))
    return "|".join(str(p) for p in parts)


async def _db_poll_loop(
    websocket: WebSocket,
    data_service: Any,
    workflow_id: str,
    initial_fingerprint: str = "",
) -> None:
    """Poll DB for workflow changes and push snapshots.

    Enables real-time updates for workflows started in a separate
    process (e.g. ``temper-ai run``) by periodically reading the shared
    database and sending updated snapshots over WebSocket.

    DB queries run in a thread executor to avoid blocking the async
    event loop (critical for PostgreSQL where queries involve network I/O).
    """
    last_fingerprint = initial_fingerprint
    while True:
        await asyncio.sleep(DB_POLL_INTERVAL_SECONDS)  # intentional polling interval
        try:
            snapshot = await asyncio.to_thread(
                data_service.get_workflow_snapshot, workflow_id,
            )
            if not snapshot:
                continue
            fp = _workflow_fingerprint(snapshot)
            if fp == last_fingerprint:
                continue
            last_fingerprint = fp
            await websocket.send_json({"type": "snapshot", "workflow": snapshot})
            if snapshot.get("status") in TERMINAL_STATUSES:
                break
        except (ConnectionError, OSError, RuntimeError):
            break  # WebSocket disconnected
        except Exception:
            logger.warning(
                "DB poll error for workflow %s; will retry",
                workflow_id, exc_info=True,
            )


def create_ws_endpoint(data_service: Any) -> Callable:
    """Create WebSocket endpoint handler.

    Returns an async callable suitable for ``app.add_api_websocket_route``.
    """

    async def websocket_handler(websocket: WebSocket, workflow_id: str) -> None:
        """Handle WebSocket connection for real-time workflow updates."""
        await websocket.accept()

        subscription_id = None
        event_queue: asyncio.Queue = asyncio.Queue(maxsize=EVENT_QUEUE_MAXSIZE)
        chunk_buffer: List[dict] = []
        chunk_lock = asyncio.Lock()

        # Create event callback
        on_event = _create_event_callback(workflow_id, event_queue, chunk_buffer)

        flush_task = None
        poll_task = None
        try:
            # Send initial snapshot (run in thread to avoid blocking event loop)
            snapshot = await asyncio.to_thread(
                data_service.get_workflow_snapshot, workflow_id,
            )
            initial_fp = ""
            if snapshot:
                await websocket.send_json({"type": "snapshot", "workflow": snapshot})
                initial_fp = _workflow_fingerprint(snapshot)

            # Subscribe to events for this workflow
            logger.info("[WebSocket] Subscribing to events for workflow %s", workflow_id)
            subscription_id = data_service.subscribe_workflow(workflow_id, on_event)
            logger.info("[WebSocket] Subscription ID: %s", subscription_id)

            # Start chunk flusher
            flush_task = asyncio.create_task(
                _flush_chunks_task(websocket, chunk_buffer, chunk_lock),
            )

            # Start DB poller for cross-process workflow updates
            poll_task = asyncio.create_task(
                _db_poll_loop(websocket, data_service, workflow_id, initial_fp),
            )

            # Stream events with heartbeat
            await _stream_events_loop(websocket, event_queue)

        except WebSocketDisconnect:
            logger.debug("WebSocket disconnected for workflow %s", workflow_id)
        except (ConnectionError, OSError, RuntimeError):
            logger.warning("WebSocket error", exc_info=True)
        finally:
            for task in (flush_task, poll_task):
                if task is not None:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            if subscription_id:
                data_service.unsubscribe(subscription_id)

    return websocket_handler
