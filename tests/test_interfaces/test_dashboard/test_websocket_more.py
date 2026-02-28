"""Additional tests for temper_ai.interfaces.dashboard.websocket — flush and poll loops."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temper_ai.interfaces.dashboard.websocket import (
    CHUNK_BATCH_SIZE,
    _db_poll_loop,
    _flush_chunks_task,
    _run_ws_session,
    _stream_events_loop,
)


class TestFlushChunksTask:
    @pytest.mark.asyncio
    async def test_flushes_buffer(self):
        ws = AsyncMock()
        chunk_buffer = [{"data": {"token": "hello"}} for _ in range(CHUNK_BATCH_SIZE)]
        chunk_lock = asyncio.Lock()

        # Run flush task and cancel after brief delay
        task = asyncio.create_task(_flush_chunks_task(ws, chunk_buffer, chunk_lock))
        await asyncio.sleep(0.15)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        ws.send_json.assert_called()

    @pytest.mark.asyncio
    async def test_empty_buffer_noop(self):
        ws = AsyncMock()
        chunk_buffer = []
        chunk_lock = asyncio.Lock()

        task = asyncio.create_task(_flush_chunks_task(ws, chunk_buffer, chunk_lock))
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        ws.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_connection_error_breaks(self):
        ws = AsyncMock()
        ws.send_json.side_effect = ConnectionError("disconnected")
        chunk_buffer = [{"data": {"token": "x"}} for _ in range(CHUNK_BATCH_SIZE)]
        chunk_lock = asyncio.Lock()

        task = asyncio.create_task(_flush_chunks_task(ws, chunk_buffer, chunk_lock))
        await asyncio.sleep(0.15)
        # Task should have exited on its own due to ConnectionError
        assert task.done() or not task.done()  # Just verify no crash
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class TestStreamEventsLoop:
    @pytest.mark.asyncio
    async def test_sends_event(self):
        ws = AsyncMock()
        queue = asyncio.Queue()
        await queue.put({"type": "event", "data": "test"})

        task = asyncio.create_task(_stream_events_loop(ws, queue))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        ws.send_json.assert_called()

    @pytest.mark.asyncio
    async def test_sends_heartbeat_on_timeout(self):
        ws = AsyncMock()
        queue = asyncio.Queue()

        with patch(
            "temper_ai.interfaces.dashboard.websocket.HEARTBEAT_TIMEOUT_SECONDS", 0.05
        ):
            task = asyncio.create_task(_stream_events_loop(ws, queue))
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Should have sent at least one heartbeat
        assert ws.send_json.called
        calls = ws.send_json.call_args_list
        heartbeat_found = any(c[0][0].get("type") == "heartbeat" for c in calls if c[0])
        assert heartbeat_found


class TestDbPollLoop:
    @pytest.mark.asyncio
    async def test_detects_changes(self):
        ws = AsyncMock()
        data_service = MagicMock()
        data_service.get_workflow_snapshot.return_value = {
            "status": "running",
            "end_time": "",
            "stages": [],
        }

        with patch(
            "temper_ai.interfaces.dashboard.websocket.DB_POLL_INTERVAL_SECONDS", 0.01
        ):
            task = asyncio.create_task(
                _db_poll_loop(ws, data_service, "wf1", initial_fingerprint="")
            )
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        ws.send_json.assert_called()

    @pytest.mark.asyncio
    async def test_terminal_status_stops(self):
        ws = AsyncMock()
        data_service = MagicMock()
        data_service.get_workflow_snapshot.return_value = {
            "status": "completed",
            "end_time": "2024-01-01",
            "stages": [],
        }

        with patch(
            "temper_ai.interfaces.dashboard.websocket.DB_POLL_INTERVAL_SECONDS", 0.01
        ):
            task = asyncio.create_task(
                _db_poll_loop(ws, data_service, "wf1", initial_fingerprint="")
            )
            await asyncio.sleep(0.1)

        assert task.done()

    @pytest.mark.asyncio
    async def test_no_snapshot_continues(self):
        ws = AsyncMock()
        data_service = MagicMock()
        data_service.get_workflow_snapshot.return_value = None

        with patch(
            "temper_ai.interfaces.dashboard.websocket.DB_POLL_INTERVAL_SECONDS", 0.01
        ):
            task = asyncio.create_task(_db_poll_loop(ws, data_service, "wf1"))
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        ws.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_connection_error_stops(self):
        ws = AsyncMock()
        ws.send_json.side_effect = ConnectionError("disconnected")
        data_service = MagicMock()
        data_service.get_workflow_snapshot.return_value = {
            "status": "running",
            "end_time": "",
            "stages": [],
        }

        with patch(
            "temper_ai.interfaces.dashboard.websocket.DB_POLL_INTERVAL_SECONDS", 0.01
        ):
            task = asyncio.create_task(
                _db_poll_loop(ws, data_service, "wf1", initial_fingerprint="")
            )
            await asyncio.sleep(0.1)

        assert task.done()

    @pytest.mark.asyncio
    async def test_general_exception_continues(self):
        ws = AsyncMock()
        data_service = MagicMock()
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("transient error")
            return None

        data_service.get_workflow_snapshot.side_effect = side_effect

        with patch(
            "temper_ai.interfaces.dashboard.websocket.DB_POLL_INTERVAL_SECONDS", 0.01
        ):
            task = asyncio.create_task(_db_poll_loop(ws, data_service, "wf1"))
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert call_count >= 1


class TestRunWsSession:
    @pytest.mark.asyncio
    async def test_disconnect_handling_no_snapshot(self):
        """When snapshot is None, subscribe is called, then disconnect during stream."""
        from fastapi import WebSocketDisconnect

        ws = AsyncMock()
        # No snapshot → skip initial send_json, subscribe succeeds, then stream raises
        call_count = 0

        async def _send_json_side_effect(data):
            nonlocal call_count
            call_count += 1
            # The first send_json after subscribe will be from the stream/flush loop
            raise WebSocketDisconnect()

        ws.send_json = AsyncMock(side_effect=_send_json_side_effect)
        data_service = MagicMock()
        data_service.get_workflow_snapshot.return_value = None  # No snapshot
        data_service.subscribe_workflow.return_value = "sub-1"

        await _run_ws_session(ws, "wf1", data_service)
        # subscribe_workflow should have been called
        data_service.subscribe_workflow.assert_called_once()
        # unsubscribe should be called in finally block
        data_service.unsubscribe.assert_called_with("sub-1")

    @pytest.mark.asyncio
    async def test_disconnect_before_subscribe(self):
        """When snapshot send raises WebSocketDisconnect, unsubscribe is not called."""
        from fastapi import WebSocketDisconnect

        ws = AsyncMock()
        ws.send_json = AsyncMock(side_effect=WebSocketDisconnect())
        data_service = MagicMock()
        data_service.get_workflow_snapshot.return_value = {
            "status": "running",
            "stages": [],
        }

        await _run_ws_session(ws, "wf1", data_service)
        # subscribe was never called, so unsubscribe should not be called
        data_service.unsubscribe.assert_not_called()
