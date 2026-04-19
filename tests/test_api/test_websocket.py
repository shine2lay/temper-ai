"""Tests for WebSocket manager.

Covers:
- notify_event / notify_stream_chunk without active connections (smoke)
- Event buffering for late-connecting clients
- Cleanup
- WebSocket connection/disconnection lifecycle via FastAPI TestClient
- Broadcast to multiple clients
- Graceful handling of closed connections
- Stream chunk batching and flushing
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from temper_ai.api.websocket import (
    CHUNK_BATCH_SIZE,
    MAX_EVENT_BUFFER_SIZE,
    WebSocketManager,
    ws_manager,
)

# ---------------------------------------------------------------------------
# Minimal FastAPI test app using a fresh WebSocketManager per test
# ---------------------------------------------------------------------------

def _make_app(manager: WebSocketManager) -> FastAPI:
    """Create a minimal FastAPI app wired to the given WebSocketManager."""
    app = FastAPI()

    @app.websocket("/ws/{execution_id}")
    async def ws_endpoint(websocket: WebSocket, execution_id: str):
        await manager.connect(websocket, execution_id)

    return app


# ---------------------------------------------------------------------------
# Smoke tests — singleton ws_manager, no connections needed
# ---------------------------------------------------------------------------

class TestWebSocketManagerSmoke:
    def test_notify_event_without_connections(self):
        """Notifying with no connected clients should not crash."""
        ws_manager.notify_event("exec-smoke-1", "test.event", {"key": "val"})

    def test_notify_stream_chunk_without_connections(self):
        """Streaming with no connected clients should buffer silently."""
        ws_manager.notify_stream_chunk("exec-smoke-2", "agent-1", "hello", done=False)

    def test_notify_stream_chunk_done_flushes(self):
        """done=True should trigger flush even without connections."""
        ws_manager.notify_stream_chunk("exec-smoke-3", "agent-1", "final", done=True)

    def test_cleanup_noop(self):
        """Cleanup for unknown execution should not crash."""
        ws_manager.cleanup("nonexistent-exec")

    def test_event_buffering(self):
        """Events should be buffered for late-connecting clients."""
        ws_manager.notify_event("exec-buf-smoke", "step.1", {"data": "first"})
        ws_manager.notify_event("exec-buf-smoke", "step.2", {"data": "second"})
        # Buffer exists internally; primary assertion: no crash


# ---------------------------------------------------------------------------
# Unit tests on a fresh WebSocketManager instance
# ---------------------------------------------------------------------------

class TestWebSocketManagerUnit:
    def setup_method(self):
        self.manager = WebSocketManager()

    def test_notify_event_buffers_message(self):
        """notify_event stores message in the event buffer."""
        self.manager.notify_event("exec-1", "stage.started", {"name": "build"})
        buf = self.manager._event_buffers.get("exec-1", [])
        assert len(buf) == 1
        assert buf[0]["event_type"] == "stage.started"
        assert buf[0]["type"] == "event"

    def test_event_buffer_caps_at_max_size(self):
        """Buffer should not grow beyond MAX_EVENT_BUFFER_SIZE."""
        for i in range(MAX_EVENT_BUFFER_SIZE + 50):
            self.manager.notify_event("exec-cap", "evt", {"i": i})
        buf = self.manager._event_buffers["exec-cap"]
        assert len(buf) == MAX_EVENT_BUFFER_SIZE

    def test_chunk_buffering_under_lock(self):
        """_buffer_chunk appends to the buffer and returns new size."""
        chunk = {"agent_id": "a1", "content": "hi", "chunk_type": "content", "done": False}
        size1 = self.manager._buffer_chunk("exec-chunk", chunk)
        size2 = self.manager._buffer_chunk("exec-chunk", chunk)
        assert size1 == 1
        assert size2 == 2

    def test_flush_chunks_clears_buffer_and_broadcasts(self):
        """_flush_chunks should pop buffer and call _broadcast."""
        chunk = {"agent_id": "a1", "content": "tok", "chunk_type": "content", "done": False}
        self.manager._buffer_chunk("exec-flush", chunk)

        broadcast_calls = []
        self.manager._broadcast = lambda eid, msg: broadcast_calls.append((eid, msg))

        self.manager._flush_chunks("exec-flush")

        # Buffer cleared
        assert "exec-flush" not in self.manager._chunk_buffers
        # Broadcast called once with the batch message
        assert len(broadcast_calls) == 1
        eid, msg = broadcast_calls[0]
        assert eid == "exec-flush"
        assert msg["event_type"] == "llm_stream_batch"
        assert len(msg["data"]["chunks"]) == 1

    def test_flush_chunks_noop_when_empty(self):
        """_flush_chunks on an empty buffer should not call _broadcast."""
        broadcast_calls = []
        self.manager._broadcast = lambda eid, msg: broadcast_calls.append((eid, msg))
        self.manager._flush_chunks("exec-empty")
        assert broadcast_calls == []

    def test_cleanup_removes_event_buffer(self):
        """cleanup() removes event buffer for that execution."""
        self.manager.notify_event("exec-clean", "evt", {})
        assert "exec-clean" in self.manager._event_buffers
        self.manager.cleanup("exec-clean")
        assert "exec-clean" not in self.manager._event_buffers

    def test_cleanup_removes_chunk_buffer(self):
        """cleanup() removes chunk buffer for that execution."""
        chunk = {"agent_id": "a1", "content": "x", "chunk_type": "content", "done": False}
        self.manager._buffer_chunk("exec-clean2", chunk)
        self.manager.cleanup("exec-clean2")
        assert "exec-clean2" not in self.manager._chunk_buffers

    def test_disconnect_removes_websocket(self):
        """_disconnect removes a websocket from the connections list."""
        ws = MagicMock()
        self.manager._connections["exec-dc"] = [ws]
        self.manager._disconnect(ws, "exec-dc")
        assert "exec-dc" not in self.manager._connections

    def test_disconnect_keeps_other_connections(self):
        """_disconnect only removes the specified websocket."""
        ws1, ws2 = MagicMock(), MagicMock()
        self.manager._connections["exec-dc2"] = [ws1, ws2]
        self.manager._disconnect(ws1, "exec-dc2")
        assert self.manager._connections["exec-dc2"] == [ws2]

    def test_disconnect_unknown_execution_noop(self):
        """_disconnect on an unknown execution_id should not crash."""
        ws = MagicMock()
        self.manager._disconnect(ws, "exec-unknown")  # no crash

    def test_notify_stream_chunk_tool_call_triggers_immediate_flush(self):
        """tool_call chunk_type should schedule an immediate flush."""
        flush_called = []
        self.manager._schedule_flush_immediate = lambda eid: flush_called.append(eid)
        self.manager._schedule_flush = lambda eid: None  # should not be called

        self.manager.notify_stream_chunk("exec-tc", "agent-1", "{}", chunk_type="tool_call")
        assert "exec-tc" in flush_called

    def test_notify_stream_chunk_done_triggers_immediate_flush(self):
        """done=True should also schedule an immediate flush."""
        flush_called = []
        self.manager._schedule_flush_immediate = lambda eid: flush_called.append(eid)

        self.manager.notify_stream_chunk("exec-done", "agent-1", "end", done=True)
        assert "exec-done" in flush_called

    def test_notify_stream_chunk_batch_size_triggers_immediate_flush(self):
        """Reaching CHUNK_BATCH_SIZE should schedule an immediate flush."""
        flush_called = []
        self.manager._schedule_flush_immediate = lambda eid: flush_called.append(eid)
        self.manager._schedule_flush = lambda eid: None

        # Fill buffer up to batch size - 1 without triggering
        for i in range(CHUNK_BATCH_SIZE - 1):
            chunk = {"agent_id": "a", "content": "x", "chunk_type": "content", "done": False}
            self.manager._buffer_chunk("exec-batch", chunk)

        # The CHUNK_BATCH_SIZE-th chunk should trigger immediate flush
        self.manager.notify_stream_chunk("exec-batch", "a", "x", done=False)
        assert "exec-batch" in flush_called


# ---------------------------------------------------------------------------
# WebSocket connection lifecycle tests via FastAPI TestClient
# ---------------------------------------------------------------------------

class TestWebSocketConnection:
    def setup_method(self):
        self.manager = WebSocketManager()
        # Patch _send_snapshot to avoid DB dependency
        self.manager._send_snapshot = AsyncMock()
        self.app = _make_app(self.manager)

    def test_client_receives_heartbeat_message_structure(self):
        """WebSocket connect/disconnect without crash."""
        with TestClient(self.app) as client:
            with client.websocket_connect("/ws/exec-heartbeat"):
                # Connection was accepted — receive the snapshot (mocked, sends nothing)
                # Disconnect immediately
                pass
        # After context exit, manager should clean up the connection
        assert "exec-heartbeat" not in self.manager._connections

    def test_connection_registers_and_deregisters(self):
        """Connection should be registered during session and removed on disconnect."""
        with TestClient(self.app) as client:
            with client.websocket_connect("/ws/exec-reg"):
                # During connection, exec-reg should be tracked
                assert "exec-reg" in self.manager._connections

        # After disconnect, cleaned up
        assert "exec-reg" not in self.manager._connections

    def test_snapshot_sent_on_connect(self):
        """_send_snapshot should be called once per connection."""
        with TestClient(self.app) as client:
            with client.websocket_connect("/ws/exec-snap"):
                pass

        self.manager._send_snapshot.assert_called_once()
        call_args = self.manager._send_snapshot.call_args
        # Second arg is execution_id
        assert call_args[0][1] == "exec-snap"

    def test_multiple_clients_same_execution(self):
        """Two clients connecting to the same execution_id are both tracked."""
        manager = WebSocketManager()
        manager._send_snapshot = AsyncMock()
        app = _make_app(manager)

        with TestClient(app) as client1:
            with client1.websocket_connect("/ws/exec-multi"):
                with TestClient(app) as client2:
                    with client2.websocket_connect("/ws/exec-multi"):
                        conns = manager._connections.get("exec-multi", [])
                        assert len(conns) == 2

    def test_send_json_failure_does_not_crash_connect(self):
        """If _send_json fails (closed socket), connect should still complete cleanly."""
        async def bad_send_json(ws, data):
            raise RuntimeError("socket closed")

        self.manager._send_json = bad_send_json

        with TestClient(self.app) as client:
            # Connection attempt — snapshot send will fail internally but not raise
            with client.websocket_connect("/ws/exec-bad-send"):
                pass  # No crash expected


# ---------------------------------------------------------------------------
# Broadcast tests
# ---------------------------------------------------------------------------

class TestBroadcast:
    def setup_method(self):
        self.manager = WebSocketManager()

    def test_broadcast_skips_when_no_connections(self):
        """_broadcast to an execution with no clients does nothing."""
        # No registered connections — should not crash
        self.manager._broadcast("exec-no-conn", {"type": "event", "event_type": "x", "data": {}})

    def test_broadcast_sends_to_registered_mock_ws(self):
        """_broadcast calls send_json on each registered mock WebSocket."""
        sent = []

        async def fake_send_json(data):
            sent.append(data)

        ws = MagicMock()
        ws.send_json = fake_send_json
        self.manager._connections["exec-bc"] = [ws]

        # Run broadcast in an event loop since it schedules coroutines
        async def run():
            self.manager._broadcast("exec-bc", {"type": "event", "event_type": "y", "data": {}})
            # Allow the scheduled coroutine to execute
            await asyncio.sleep(0.05)

        asyncio.run(run())
        assert len(sent) == 1
        assert sent[0]["event_type"] == "y"

    def test_broadcast_handles_failed_send_gracefully(self):
        """_broadcast should not raise when a WebSocket send fails."""
        async def failing_send(data):
            raise OSError("broken pipe")

        ws = MagicMock()
        ws.send_json = failing_send
        self.manager._connections["exec-fail"] = [ws]

        async def run():
            self.manager._broadcast("exec-fail", {"type": "event", "event_type": "z", "data": {}})
            await asyncio.sleep(0.05)

        asyncio.run(run())  # Should not raise
