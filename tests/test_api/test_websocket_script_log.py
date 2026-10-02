"""Script log rows on a run's socket: in-process rows go to every viewer of the run; a subprocess
worker's come from Redis, to each socket from where the stream was when that socket connected."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from temper_ai.api.websocket import WebSocketManager
from temper_ai.observability.script_logs import LIVE_ROW_MAX_BYTES


def _row(seq: int, text: str = "hello\n") -> dict:
    return {"attempt_id": "a1", "seq": seq, "bytes": len(text.encode()),
            "entries": [{"stream": "stdout", "t": "2026-10-02T12:00:00.000+00:00", "text": text}]}


def _sent_to_one_socket(manager: WebSocketManager, run: str, call) -> list[dict]:
    sent: list[dict] = []

    async def send_json(data):
        sent.append(data)

    ws = MagicMock()
    ws.send_json = send_json
    manager._connections[run] = [ws]

    async def go():
        call()
        await asyncio.sleep(0.05)

    asyncio.run(go())
    return sent


class TestInProcessRows:
    def test_a_row_goes_to_the_run_s_viewers_as_its_own_message(self):
        manager = WebSocketManager()
        sent = _sent_to_one_socket(manager, "run-1", lambda: manager.notify_script_log("run-1", _row(1)))
        assert sent == [{"type": "script_log", "execution_id": "run-1", "data": _row(1)}]

    def test_a_large_row_goes_without_its_text(self):
        manager = WebSocketManager()
        big = _row(2, "x" * (LIVE_ROW_MAX_BYTES + 1))
        [msg] = _sent_to_one_socket(manager, "run-1", lambda: manager.notify_script_log("run-1", big))
        assert msg["data"]["stub"] is True and "entries" not in msg["data"]

    def test_rows_are_not_kept_for_late_viewers(self):
        manager = WebSocketManager()
        manager.notify_script_log("run-1", _row(1))
        assert manager._event_buffers.get("run-1", []) == []


class FakeSubscriber:
    """Stands in for RedisChunkSubscriber: no chunks, and the given script log rows."""

    position: str | None = "7-0"
    rows: list[dict] = []
    instances: list[FakeSubscriber] = []

    def __init__(self, url=None):
        self.enabled = True
        self.read_from: str | None = None
        self.closed = False
        FakeSubscriber.instances.append(self)

    async def subscribe(self, execution_id, *, from_id="0"):
        return
        yield  # pragma: no cover

    async def script_log_position(self, execution_id):
        return FakeSubscriber.position

    async def subscribe_script_logs(self, execution_id, *, from_id):
        self.read_from = from_id
        for row in FakeSubscriber.rows:
            yield row
        await asyncio.sleep(3600)  # the run goes on until the socket closes

    async def close(self):
        self.closed = True


@pytest.fixture
def fake_redis(monkeypatch):
    import temper_ai.streaming as streaming

    FakeSubscriber.instances = []
    FakeSubscriber.position = "7-0"
    FakeSubscriber.rows = [_row(1), _row(2)]
    monkeypatch.setattr(streaming, "RedisChunkSubscriber", FakeSubscriber)
    return FakeSubscriber


def _app(manager: WebSocketManager) -> FastAPI:
    app = FastAPI()

    @app.websocket("/ws/{execution_id}")
    async def ws_endpoint(websocket: WebSocket, execution_id: str):
        await manager.connect(websocket, execution_id)

    return app


class TestSubprocessRows:
    def test_a_socket_gets_the_rows_from_where_the_stream_was(self, fake_redis):
        manager = WebSocketManager()
        manager._send_snapshot = AsyncMock()
        with TestClient(_app(manager)) as client, client.websocket_connect("/ws/run-1") as ws:
            got = [ws.receive_json(), ws.receive_json()]
        assert got == [{"type": "script_log", "execution_id": "run-1", "data": _row(1)},
                       {"type": "script_log", "execution_id": "run-1", "data": _row(2)}]
        readers = [s for s in fake_redis.instances if s.read_from is not None]
        assert [s.read_from for s in readers] == ["7-0"]

    def test_closing_the_socket_stops_its_reader(self, fake_redis):
        manager = WebSocketManager()
        manager._send_snapshot = AsyncMock()
        with TestClient(_app(manager)) as client:
            with client.websocket_connect("/ws/run-1") as ws:
                ws.receive_json()
            [reader] = [s for s in fake_redis.instances if s.read_from is not None]
            deadline = time.monotonic() + 5
            while not reader.closed and time.monotonic() < deadline:
                time.sleep(0.02)
        assert reader.closed
        assert "run-1" not in manager._connections

    def test_an_ended_stream_starts_no_reader(self, fake_redis):
        fake_redis.position = None
        manager = WebSocketManager()

        async def go():
            return await manager._start_script_log_forwarder(MagicMock(), "run-1")

        assert asyncio.run(go()) is None
        assert all(s.closed for s in fake_redis.instances)

    def test_without_redis_there_is_no_reader(self, monkeypatch):
        monkeypatch.delenv("TEMPER_REDIS_URL", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        manager = WebSocketManager()

        async def go():
            return await manager._start_script_log_forwarder(MagicMock(), "run-1")

        assert asyncio.run(go()) is None
