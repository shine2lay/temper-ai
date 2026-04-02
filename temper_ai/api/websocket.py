"""WebSocket manager — real-time event streaming to frontend.

Protocol:
1. Client connects to /ws/{execution_id}
2. Server sends snapshot (full current state)
3. Server streams events as they arrive
4. Server sends heartbeat every 30s if idle

Message format:
- Snapshot:  {"type": "snapshot", "workflow": WorkflowExecution}
- Event:    {"type": "event", "event_type": str, "data": dict, "timestamp": str}
- Heartbeat: {"type": "heartbeat", "timestamp": str}
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict
from datetime import UTC, datetime
from fastapi import WebSocket, WebSocketDisconnect

from temper_ai.api.data_service import get_workflow_execution

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30  # seconds
CHUNK_BATCH_SIZE = 10  # flush after this many buffered chunks
CHUNK_FLUSH_MS = 50  # flush interval in milliseconds


class WebSocketManager:
    """Manages WebSocket connections for real-time execution updates.

    In-process event distribution — events are pushed by the executor
    via notify_event(), and broadcast to all connected clients for that
    execution_id.

    Stream chunks are batched to avoid flooding WebSocket with per-token
    messages. Chunks are buffered and flushed either when the buffer reaches
    CHUNK_BATCH_SIZE or every CHUNK_FLUSH_MS milliseconds.
    """

    def __init__(self):
        # execution_id → list of connected WebSockets
        self._connections: dict[str, list[WebSocket]] = {}
        # execution_id → list of buffered events (for connections that arrive late)
        self._event_buffers: dict[str, list[dict]] = {}
        # Stream chunk buffer: execution_id → list of chunk dicts
        self._chunk_buffers: dict[str, list[dict]] = defaultdict(list)
        self._chunk_lock = threading.Lock()
        self._flush_scheduled: set[str] = set()

    async def connect(self, websocket: WebSocket, execution_id: str):
        """Handle a new WebSocket connection."""
        await websocket.accept()

        # Capture the event loop for cross-thread chunk flushing
        self._main_loop = asyncio.get_running_loop()

        # Register connection
        if execution_id not in self._connections:
            self._connections[execution_id] = []
        self._connections[execution_id].append(websocket)

        logger.info("WebSocket connected for execution %s", execution_id)

        try:
            # Send snapshot of current state — this contains all data up to now,
            # so we skip replaying buffered events (they'd overwrite correct statuses)
            await self._send_snapshot(websocket, execution_id)

            # Keep connection alive with heartbeats
            while True:
                try:
                    # Wait for client messages (ping/pong) or timeout for heartbeat
                    await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=HEARTBEAT_INTERVAL,
                    )
                except asyncio.TimeoutError:
                    # Send heartbeat
                    await self._send_json(websocket, {
                        "type": "heartbeat",
                        "timestamp": datetime.now(UTC).isoformat(),
                    })

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected for execution %s", execution_id)
        except Exception as exc:
            logger.warning("WebSocket error for %s: %s", execution_id, exc)
        finally:
            self._disconnect(websocket, execution_id)

    def notify_event(self, execution_id: str, event_type: str, data: dict):
        """Called by the executor when an event occurs. Broadcasts to all connected clients.

        This is called from a sync context (the executor thread). We schedule
        the async broadcast on the event loop.
        """
        message = {
            "type": "event",
            "event_type": event_type,
            "data": data,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        # Buffer for late-connecting clients (skip stream chunks — they're transient)
        if execution_id not in self._event_buffers:
            self._event_buffers[execution_id] = []
        self._event_buffers[execution_id].append(message)

        self._broadcast(execution_id, message)

    def notify_stream_chunk(
        self,
        execution_id: str,
        agent_id: str,
        content: str,
        chunk_type: str = "content",
        done: bool = False,
    ):
        """Buffer a stream chunk for batched delivery.

        Called from executor threads for each LLM token. Chunks are accumulated
        and flushed as a single 'llm_stream_batch' message to reduce WebSocket overhead.
        """
        chunk = {"agent_id": agent_id, "content": content, "chunk_type": chunk_type, "done": done}
        buffer_size = self._buffer_chunk(execution_id, chunk)

        if buffer_size >= CHUNK_BATCH_SIZE or done:
            self._flush_chunks(execution_id)
        elif execution_id not in self._flush_scheduled:
            self._schedule_flush(execution_id)

    def _buffer_chunk(self, execution_id: str, chunk: dict) -> int:
        """Append chunk to the buffer under lock. Returns the new buffer size."""
        with self._chunk_lock:
            self._chunk_buffers[execution_id].append(chunk)
            return len(self._chunk_buffers[execution_id])

    def _schedule_flush(self, execution_id: str) -> None:
        """Schedule a delayed flush on the event loop (sync-safe)."""
        self._flush_scheduled.add(execution_id)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.call_later(CHUNK_FLUSH_MS / 1000, self._flush_chunks, execution_id)
            return

        self._schedule_flush_threadsafe(execution_id)

    def _schedule_flush_threadsafe(self, execution_id: str) -> None:
        """Schedule a delayed flush via call_soon_threadsafe (from a non-async thread)."""
        main_loop = getattr(self, '_main_loop', None)
        try:
            if main_loop and main_loop.is_running():
                main_loop.call_soon_threadsafe(
                    main_loop.call_later,
                    CHUNK_FLUSH_MS / 1000,
                    self._flush_chunks, execution_id,
                )
            else:
                self._flush_chunks(execution_id)
        except Exception:  # noqa: broad-except
            self._flush_chunks(execution_id)

    def _flush_chunks(self, execution_id: str):
        """Flush buffered chunks as a single batch message."""
        self._flush_scheduled.discard(execution_id)

        with self._chunk_lock:
            chunks = self._chunk_buffers.pop(execution_id, [])

        if not chunks:
            return

        message = {
            "type": "event",
            "event_type": "llm_stream_batch",
            "data": {"chunks": chunks},
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._broadcast(execution_id, message)

    def _broadcast(self, execution_id: str, message: dict):
        """Send a message to all connected WebSockets for an execution."""
        connections = self._connections.get(execution_id, [])
        for ws in connections:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self._send_json(ws, message))
                else:
                    loop.run_until_complete(self._send_json(ws, message))
            except Exception:
                logger.debug("Failed to send to WebSocket", exc_info=True)

    def cleanup(self, execution_id: str):
        """Clean up buffers for a completed execution."""
        self._event_buffers.pop(execution_id, None)
        with self._chunk_lock:
            self._chunk_buffers.pop(execution_id, None)
        self._flush_scheduled.discard(execution_id)

    async def _send_snapshot(self, websocket: WebSocket, execution_id: str):
        """Send full current state as snapshot."""
        workflow = get_workflow_execution(execution_id)
        if workflow:
            await self._send_json(websocket, {
                "type": "snapshot",
                "workflow": workflow,
            })

    async def _send_json(self, websocket: WebSocket, data: dict):
        """Send JSON message to a WebSocket."""
        try:
            await websocket.send_json(data)
        except Exception: # noqa
            pass  # Connection might be closing  # noqa: B110

    def _disconnect(self, websocket: WebSocket, execution_id: str):
        """Remove a disconnected WebSocket."""
        connections = self._connections.get(execution_id, [])
        if websocket in connections:
            connections.remove(websocket)
        if not connections:
            self._connections.pop(execution_id, None)


# Singleton instance
ws_manager = WebSocketManager()
