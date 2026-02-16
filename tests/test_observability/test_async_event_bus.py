"""Tests for AsyncObservabilityEventBus."""
import asyncio
from datetime import datetime, timezone

import pytest

from src.observability.event_bus import (
    AsyncObservabilityEventBus,
    ObservabilityEvent,
)


def _make_event(event_type: str = "test") -> ObservabilityEvent:
    return ObservabilityEvent(
        event_type=event_type,
        timestamp=datetime.now(timezone.utc),
        data={"key": "value"},
    )


class TestAsyncEventBusBasics:
    """Test basic async event bus operations."""

    @pytest.mark.asyncio
    async def test_emit_and_receive(self):
        bus = AsyncObservabilityEventBus()
        received = []
        bus.subscribe(lambda e: received.append(e))
        bus.start()
        bus.emit(_make_event("workflow_start"))
        await asyncio.sleep(0.05)  # intentional: wait for drain
        await bus.stop()
        assert len(received) == 1
        assert received[0].event_type == "workflow_start"

    @pytest.mark.asyncio
    async def test_event_type_filtering(self):
        bus = AsyncObservabilityEventBus()
        received = []
        bus.subscribe(lambda e: received.append(e), event_types={"stage_start"})
        bus.start()
        bus.emit(_make_event("workflow_start"))
        bus.emit(_make_event("stage_start"))
        await asyncio.sleep(0.05)  # intentional: wait for drain
        await bus.stop()
        assert len(received) == 1
        assert received[0].event_type == "stage_start"

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        bus = AsyncObservabilityEventBus()
        received = []
        sub_id = bus.subscribe(lambda e: received.append(e))
        bus.unsubscribe(sub_id)
        bus.start()
        bus.emit(_make_event())
        await asyncio.sleep(0.05)  # intentional: wait for drain
        await bus.stop()
        assert len(received) == 0


class TestAsyncEventBusEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_queue_full_drops_event(self):
        bus = AsyncObservabilityEventBus(maxsize=2)
        # Don't start - queue will fill up without draining
        bus.emit(_make_event("e1"))
        bus.emit(_make_event("e2"))
        # Third should be dropped (queue full)
        bus.emit(_make_event("e3"))
        assert bus._queue.qsize() == 2

    @pytest.mark.asyncio
    async def test_subscriber_exception_doesnt_crash(self):
        bus = AsyncObservabilityEventBus()
        good_received = []

        def bad_callback(e):
            raise RuntimeError("subscriber error")

        bus.subscribe(bad_callback)
        bus.subscribe(lambda e: good_received.append(e))
        bus.start()
        bus.emit(_make_event())
        await asyncio.sleep(0.1)  # intentional: wait for drain + error handling
        await bus.stop()
        assert len(good_received) == 1

    @pytest.mark.asyncio
    async def test_async_subscriber(self):
        bus = AsyncObservabilityEventBus()
        received = []

        async def async_callback(e):
            await asyncio.sleep(0.01)  # intentional: simulate async work
            received.append(e)

        bus.subscribe(async_callback)
        bus.start()
        bus.emit(_make_event())
        await asyncio.sleep(0.1)  # intentional: wait for drain
        await bus.stop()
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        bus = AsyncObservabilityEventBus()
        await bus.stop()  # Should not raise
        assert not bus._started

    @pytest.mark.asyncio
    async def test_double_start(self):
        bus = AsyncObservabilityEventBus()
        bus.start()
        bus.start()  # Should not create duplicate tasks
        await bus.stop()
        assert not bus._started

    @pytest.mark.asyncio
    async def test_drain_processes_remaining(self):
        bus = AsyncObservabilityEventBus()
        received = []
        bus.subscribe(lambda e: received.append(e))
        bus.start()
        for i in range(5):
            bus.emit(_make_event(f"event_{i}"))
        await bus.stop(drain=True)
        assert len(received) == 5
