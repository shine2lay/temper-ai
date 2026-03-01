"""Extended tests for temper_ai.interfaces.dashboard.websocket."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temper_ai.interfaces.dashboard.websocket import (
    TERMINAL_STATUSES,
    _cancel_background_tasks,
    _create_event_callback,
    _validate_ws_auth,
    _workflow_fingerprint,
    create_ws_endpoint,
)


class TestCreateEventCallback:
    def test_non_chunk_event_queued(self):
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue(maxsize=100)
        chunk_buffer = []

        event = MagicMock()
        event.event_type = "workflow_started"
        event.timestamp = MagicMock()
        event.timestamp.isoformat.return_value = "2024-01-01T00:00:00"
        event.data = {}
        event.workflow_id = "wf1"
        event.stage_id = "s1"
        event.agent_id = "a1"

        callback = _create_event_callback("wf1", queue, chunk_buffer, loop)
        # Run callback in the loop context
        loop.run_until_complete(asyncio.sleep(0))
        callback(event)
        assert queue.qsize() == 1
        loop.close()

    def test_chunk_event_buffered(self):
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue(maxsize=100)
        chunk_buffer = []

        event = MagicMock()
        event.event_type = "llm_stream_chunk"
        event.timestamp = MagicMock()
        event.timestamp.isoformat.return_value = "2024-01-01T00:00:00"
        event.data = {"token": "hi"}
        event.workflow_id = "wf1"
        event.stage_id = "s1"
        event.agent_id = "a1"

        callback = _create_event_callback("wf1", queue, chunk_buffer, loop)

        # Use call_soon_threadsafe from the loop
        # Since we call directly, the append happens via loop.call_soon_threadsafe
        callback(event)

        # Process pending callbacks
        loop.run_until_complete(asyncio.sleep(0.01))
        assert len(chunk_buffer) == 1
        assert queue.qsize() == 0
        loop.close()

    def test_stream_token_buffered(self):
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue(maxsize=100)
        chunk_buffer = []

        event = MagicMock()
        event.event_type = "stream_token"
        event.timestamp = MagicMock()
        event.timestamp.isoformat.return_value = "2024-01-01T00:00:00"
        event.data = {"token": "world"}
        event.workflow_id = "wf1"
        event.stage_id = "s1"
        event.agent_id = "a1"

        callback = _create_event_callback("wf1", queue, chunk_buffer, loop)
        callback(event)

        loop.run_until_complete(asyncio.sleep(0.01))
        assert len(chunk_buffer) == 1
        loop.close()

    def test_queue_full_drops_event(self):
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue(maxsize=1)
        chunk_buffer = []

        # Fill the queue
        event1 = MagicMock()
        event1.event_type = "event1"
        event1.timestamp = MagicMock()
        event1.timestamp.isoformat.return_value = "t1"
        event1.data = {}
        event1.workflow_id = "wf1"
        event1.stage_id = "s1"
        event1.agent_id = "a1"

        callback = _create_event_callback("wf1", queue, chunk_buffer, loop)
        callback(event1)
        assert queue.qsize() == 1

        # Second event should be dropped (queue full)
        event2 = MagicMock()
        event2.event_type = "event2"
        event2.timestamp = MagicMock()
        event2.timestamp.isoformat.return_value = "t2"
        event2.data = {}
        event2.workflow_id = "wf1"
        event2.stage_id = "s1"
        event2.agent_id = "a1"

        callback(event2)  # Should not raise
        assert queue.qsize() == 1
        loop.close()


class TestWorkflowFingerprint:
    def test_empty_snapshot(self):
        fp = _workflow_fingerprint({})
        assert fp == "|"

    def test_with_stages(self):
        snapshot = {
            "status": "running",
            "end_time": "",
            "stages": [
                {
                    "status": "completed",
                    "agents": [{"status": "done"}],
                },
            ],
        }
        fp = _workflow_fingerprint(snapshot)
        assert "running" in fp
        assert "completed" in fp
        assert "done" in fp

    def test_terminal_statuses(self):
        assert "completed" in TERMINAL_STATUSES
        assert "failed" in TERMINAL_STATUSES


class TestValidateWsAuth:
    @pytest.mark.asyncio
    @patch("temper_ai.auth.ws_tickets.validate_ws_ticket")
    async def test_valid_ticket(self, mock_validate):
        mock_validate.return_value = MagicMock()
        ws = MagicMock()
        ws.query_params = {"ticket": "valid-ticket"}

        result = await _validate_ws_auth(ws)
        assert result is True

    @pytest.mark.asyncio
    @patch("temper_ai.auth.ws_tickets.validate_ws_ticket")
    async def test_invalid_ticket(self, mock_validate):
        mock_validate.return_value = None
        ws = AsyncMock()
        ws.query_params = {"ticket": "invalid-ticket"}

        result = await _validate_ws_auth(ws)
        assert result is False
        # _validate_ws_auth no longer closes the socket; caller is responsible
        ws.close.assert_not_called()

    @pytest.mark.asyncio
    @patch("temper_ai.auth.api_key_auth.authenticate_ws_token")
    async def test_valid_token(self, mock_auth):
        mock_auth.return_value = MagicMock()
        ws = MagicMock()
        ws.query_params = {"token": "valid-token"}

        result = await _validate_ws_auth(ws)
        assert result is True

    @pytest.mark.asyncio
    @patch("temper_ai.auth.api_key_auth.authenticate_ws_token")
    async def test_invalid_token(self, mock_auth):
        mock_auth.return_value = None
        ws = AsyncMock()
        ws.query_params = {"token": "invalid"}

        result = await _validate_ws_auth(ws)
        assert result is False

    @pytest.mark.asyncio
    async def test_no_auth_params(self):
        ws = AsyncMock()
        ws.query_params = {}

        result = await _validate_ws_auth(ws)
        assert result is False
        # _validate_ws_auth no longer closes the socket; caller is responsible
        ws.close.assert_not_called()


class TestCancelBackgroundTasks:
    @pytest.mark.asyncio
    async def test_cancel_tasks(self):
        async def dummy():
            await asyncio.sleep(100)

        task1 = asyncio.create_task(dummy())
        await _cancel_background_tasks(task1, None)
        assert task1.cancelled()

    @pytest.mark.asyncio
    async def test_cancel_already_done_task(self):
        async def fast():
            return 42

        task = asyncio.create_task(fast())
        await asyncio.sleep(0.01)  # let it complete
        await _cancel_background_tasks(task)


class TestCreateWsEndpoint:
    def test_no_auth(self):
        ds = MagicMock()
        handler = create_ws_endpoint(ds, auth_enabled=False)
        assert callable(handler)

    def test_with_auth(self):
        ds = MagicMock()
        handler = create_ws_endpoint(ds, auth_enabled=True)
        assert callable(handler)
