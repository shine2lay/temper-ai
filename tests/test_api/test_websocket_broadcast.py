"""Broadcasting to a WebSocket from a workflow thread.

In-process execution streams LLM chunks from the agent's own thread. That
thread has no running event loop, and the old fallback called
`asyncio.run(...)`, which builds a new loop and then touches a socket
owned by uvicorn's loop. The connection died with "is bound to a different
event loop" as soon as a run started producing output, live updates
degraded to polling, and token streaming never reached the browser.
"""

import asyncio
import threading

import pytest

from temper_ai.api.websocket import WebSocketManager


class FakeWebSocket:
    """Records what was sent, and which loop sent it."""

    def __init__(self):
        self.sent: list[dict] = []
        self.loops: list[object] = []

    async def send_json(self, data):
        self.loops.append(asyncio.get_running_loop())
        self.sent.append(data)


@pytest.mark.asyncio
async def test_broadcast_from_a_thread_reaches_the_owning_loop():
    manager = WebSocketManager()
    ws = FakeWebSocket()
    manager._connections["run-1"] = [ws]
    manager._main_loop = asyncio.get_running_loop()

    errors: list[BaseException] = []

    def from_worker_thread():
        try:
            manager._broadcast("run-1", {"type": "event", "data": {"chunk": "hello"}})
        except BaseException as exc:  # noqa: BLE001 - recorded for the assert
            errors.append(exc)

    thread = threading.Thread(target=from_worker_thread)
    thread.start()
    thread.join(timeout=5)

    # Give the scheduled coroutine a turn on this loop.
    for _ in range(20):
        if ws.sent:
            break
        await asyncio.sleep(0.05)

    assert not errors, f"broadcasting from a thread raised: {errors}"
    assert ws.sent == [{"type": "event", "data": {"chunk": "hello"}}]
    # Delivered on the loop that owns the socket, not a new one.
    assert ws.loops == [asyncio.get_running_loop()]


@pytest.mark.asyncio
async def test_broadcast_on_the_loop_still_works():
    manager = WebSocketManager()
    ws = FakeWebSocket()
    manager._connections["run-1"] = [ws]
    manager._main_loop = asyncio.get_running_loop()

    manager._broadcast("run-1", {"type": "heartbeat"})
    for _ in range(20):
        if ws.sent:
            break
        await asyncio.sleep(0.05)

    assert ws.sent == [{"type": "heartbeat"}]


def test_broadcast_without_any_loop_does_not_raise():
    """A chunk arriving after shutdown must not take the caller down."""
    manager = WebSocketManager()
    ws = FakeWebSocket()
    manager._connections["run-1"] = [ws]
    manager._main_loop = None

    manager._broadcast("run-1", {"type": "event"})  # must not raise
    assert ws.sent == []


@pytest.mark.asyncio
async def test_no_connections_is_a_no_op():
    manager = WebSocketManager()
    manager._main_loop = asyncio.get_running_loop()
    manager._broadcast("nobody-listening", {"type": "event"})
