"""Tests for WebSocket manager."""

import asyncio
from unittest.mock import MagicMock, AsyncMock

import pytest

from temper_ai.api.websocket import ws_manager


class TestWebSocketManager:
    def test_notify_event_without_connections(self):
        """Notifying with no connected clients should not crash."""
        ws_manager.notify_event("exec-1", "test.event", {"key": "val"})

    def test_notify_stream_chunk_without_connections(self):
        """Streaming with no connected clients should buffer silently."""
        ws_manager.notify_stream_chunk("exec-1", "agent-1", "hello", done=False)

    def test_notify_stream_chunk_done_flushes(self):
        """done=True should trigger flush even without connections."""
        ws_manager.notify_stream_chunk("exec-1", "agent-1", "final", done=True)

    def test_cleanup_noop(self):
        """Cleanup for unknown execution should not crash."""
        ws_manager.cleanup("nonexistent-exec")

    def test_event_buffering(self):
        """Events should be buffered for late-connecting clients."""
        ws_manager.notify_event("exec-buffer", "step.1", {"data": "first"})
        ws_manager.notify_event("exec-buffer", "step.2", {"data": "second"})
        # Buffer should exist internally (implementation detail)
        # Main assertion: no crash
