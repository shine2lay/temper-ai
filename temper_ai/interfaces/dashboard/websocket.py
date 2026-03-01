"""WebSocket handler for real-time dashboard updates."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

EVENT_QUEUE_MAXSIZE = 1024
HEARTBEAT_TIMEOUT_SECONDS = 30.0
CHUNK_IDLE_TIMEOUT_SECONDS = 0.03  # 30ms adaptive idle timeout
CHUNK_BATCH_SIZE = 10  # Flush immediately when buffer reaches this size
DB_POLL_INTERVAL_SECONDS = 2.0  # DB polling interval for cross-process updates
TERMINAL_STATUSES = frozenset({"completed", "failed", "halted", "timeout"})
WS_CLOSE_AUTH_FAILED = 4001
WS_CLOSE_WORKFLOW_TERMINAL = 4100


def _create_event_callback(
    workflow_id: str,
    event_queue: asyncio.Queue,
    chunk_buffer: list[dict],
    loop: asyncio.AbstractEventLoop,
) -> Callable:
    """Create event callback for event bus subscription.

    Args:
        workflow_id: Workflow ID for logging.
        event_queue: Queue to put non-chunk events.
        chunk_buffer: Buffer for batched stream chunks.
        loop: The asyncio event loop (captured at creation time so the
            callback can schedule work from the emitting thread).

    Returns:
        Event callback function.
    """

    def on_event(event: Any) -> None:
        """Callback from event bus (runs in sync emitting thread)."""
        logger.info(
            "[WebSocket] Received event: %s for workflow %s",
            event.event_type,
            workflow_id,
        )
        event_dict = {
            "type": "event",
            "event_type": event.event_type,
            "timestamp": event.timestamp.isoformat(),
            "data": event.data,
            "workflow_id": event.workflow_id,
            "stage_id": event.stage_id,
            "agent_id": event.agent_id,
        }
        # Batch streaming chunks instead of queueing individually.
        # Both "llm_stream_chunk" (internal event bus) and "stream_token"
        # (wire-up event type for partial LLM content) are batched the same way.
        if event.event_type in ("llm_stream_chunk", "stream_token"):
            loop.call_soon_threadsafe(chunk_buffer.append, event_dict)
            return

        try:
            event_queue.put_nowait(event_dict)
        except asyncio.QueueFull:
            logger.warning("Event queue full, dropping event")

    return on_event


async def _flush_chunks_task(
    websocket: WebSocket,
    chunk_buffer: list[dict],
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
            await asyncio.sleep(
                CHUNK_IDLE_TIMEOUT_SECONDS
            )  # intentional wait for batching
        async with chunk_lock:
            if not chunk_buffer:
                continue
            batch = list(chunk_buffer)
            chunk_buffer.clear()
        try:
            await websocket.send_json(
                {
                    "type": "event",
                    "event_type": "llm_stream_batch",
                    "data": {"chunks": [c["data"] for c in batch]},
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
        except (ConnectionError, OSError, RuntimeError):
            break  # Connection closed


async def _stream_events_loop(
    websocket: WebSocket,
    event_queue: asyncio.Queue,
    done_event: asyncio.Event,
) -> None:
    """Stream events with heartbeat until done_event is set.

    Args:
        websocket: WebSocket connection.
        event_queue: Queue of events to send.
        done_event: Signalled by the DB poll loop when the workflow reaches
            a terminal state.
    """
    while not done_event.is_set():
        try:
            event_dict = await asyncio.wait_for(
                event_queue.get(), timeout=HEARTBEAT_TIMEOUT_SECONDS
            )
            await websocket.send_json(event_dict)
        except TimeoutError:
            await websocket.send_json(
                {
                    "type": "heartbeat",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
    # Terminal state reached — close gracefully so the frontend stops reconnecting.
    await websocket.close(
        code=WS_CLOSE_WORKFLOW_TERMINAL,
        reason="Workflow reached terminal state",
    )


def _workflow_fingerprint(snapshot: dict[str, Any]) -> str:
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
    done_event: asyncio.Event | None = None,
) -> None:
    """Poll DB for workflow changes and push snapshots.

    Enables real-time updates for workflows started in a separate
    process (e.g. a separate API client) by periodically reading the shared
    database and sending updated snapshots over WebSocket.

    DB queries run in a thread executor to avoid blocking the async
    event loop (critical for PostgreSQL where queries involve network I/O).
    """
    last_fingerprint = initial_fingerprint
    while True:
        await asyncio.sleep(DB_POLL_INTERVAL_SECONDS)  # intentional polling interval
        try:
            snapshot = await asyncio.to_thread(
                data_service.get_workflow_snapshot,
                workflow_id,
            )
            if not snapshot:
                continue
            fp = _workflow_fingerprint(snapshot)
            if fp == last_fingerprint:
                continue
            last_fingerprint = fp
            await websocket.send_json({"type": "snapshot", "workflow": snapshot})
            if snapshot.get("status") in TERMINAL_STATUSES:
                if done_event is not None:
                    done_event.set()
                break
        except (ConnectionError, OSError, RuntimeError):
            break  # WebSocket disconnected
        except Exception:
            logger.warning(
                "DB poll error for workflow %s; will retry",
                workflow_id,
                exc_info=True,
            )


async def _validate_ws_auth(websocket: WebSocket) -> bool:
    """Validate WebSocket authentication via ticket or token.

    Returns True if auth succeeded, False otherwise.
    Does NOT close the WebSocket — the caller is responsible for sending
    the close frame (after ``accept()`` so the close code reaches the browser).
    """
    ticket = websocket.query_params.get("ticket")
    token = websocket.query_params.get("token")  # Backward compat
    if ticket:
        from temper_ai.auth.ws_tickets import validate_ws_ticket

        ctx = validate_ws_ticket(ticket)
        if ctx is None:
            return False
    elif token:
        logging.getLogger(__name__).warning(
            "WebSocket auth via ?token= is deprecated; use /api/auth/ws-ticket"
        )
        from temper_ai.auth.api_key_auth import authenticate_ws_token

        ctx = await authenticate_ws_token(token)
        if ctx is None:
            return False
    else:
        return False
    return True


async def _cancel_background_tasks(*tasks: asyncio.Task | None) -> None:
    """Cancel and await background tasks, suppressing CancelledError."""
    for task in tasks:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


async def _run_ws_session(
    websocket: WebSocket,
    workflow_id: str,
    data_service: Any,
) -> None:
    """Run the main WebSocket session: subscribe, stream, and poll."""
    subscription_id = None
    event_queue: asyncio.Queue = asyncio.Queue(maxsize=EVENT_QUEUE_MAXSIZE)
    chunk_buffer: list[dict] = []
    chunk_lock = asyncio.Lock()
    done_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    on_event = _create_event_callback(workflow_id, event_queue, chunk_buffer, loop)

    flush_task = None
    poll_task = None
    try:
        snapshot = await asyncio.to_thread(
            data_service.get_workflow_snapshot, workflow_id
        )
        initial_fp = ""
        if snapshot:
            await websocket.send_json({"type": "snapshot", "workflow": snapshot})
            initial_fp = _workflow_fingerprint(snapshot)
            # Workflow already finished — close immediately so the frontend
            # doesn't enter a reconnect loop for a completed workflow.
            if snapshot.get("status") in TERMINAL_STATUSES:
                await websocket.close(
                    code=WS_CLOSE_WORKFLOW_TERMINAL,
                    reason="Workflow reached terminal state",
                )
                return

        logger.info("[WebSocket] Subscribing to events for workflow %s", workflow_id)
        subscription_id = data_service.subscribe_workflow(workflow_id, on_event)
        logger.info("[WebSocket] Subscription ID: %s", subscription_id)

        flush_task = asyncio.create_task(
            _flush_chunks_task(websocket, chunk_buffer, chunk_lock)
        )
        poll_task = asyncio.create_task(
            _db_poll_loop(websocket, data_service, workflow_id, initial_fp, done_event)
        )

        await _stream_events_loop(websocket, event_queue, done_event)
    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected for workflow %s", workflow_id)
    except (ConnectionError, OSError, RuntimeError):
        logger.warning("WebSocket error", exc_info=True)
    except Exception:
        logger.exception(
            "Unhandled error in WebSocket session for workflow %s", workflow_id
        )
    finally:
        await _cancel_background_tasks(flush_task, poll_task)
        if subscription_id:
            data_service.unsubscribe(subscription_id)


def create_ws_endpoint(data_service: Any, auth_enabled: bool = False) -> Callable:
    """Create WebSocket endpoint handler.

    Returns an async callable suitable for ``app.add_api_websocket_route``.
    """

    async def websocket_handler(websocket: WebSocket, workflow_id: str) -> None:
        """Handle WebSocket connection for real-time workflow updates."""
        await websocket.accept()
        if auth_enabled:
            if not await _validate_ws_auth(websocket):
                await websocket.close(code=WS_CLOSE_AUTH_FAILED, reason="Auth failed")
                return
        await _run_ws_session(websocket, workflow_id, data_service)

    return websocket_handler
