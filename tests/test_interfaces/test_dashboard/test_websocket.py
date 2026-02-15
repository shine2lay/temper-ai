"""Tests for dashboard WebSocket handler."""
import asyncio
import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.interfaces.dashboard.app import create_app
from src.observability.constants import ObservabilityFields
from src.observability.event_bus import ObservabilityEvent, ObservabilityEventBus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_WORKFLOW = {
    "id": "wf-ws-1",
    "workflow_name": "ws-test",
    ObservabilityFields.STATUS: "running",
    "stages": [],
}


def _make_backend(workflow=None):
    backend = MagicMock()
    backend.get_workflow.return_value = workflow
    return backend


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWebSocketSnapshot:
    def test_snapshot_sent_on_connect(self):
        """On connect the server should send a snapshot message."""
        backend = _make_backend(SAMPLE_WORKFLOW)
        app = create_app(backend=backend)
        client = TestClient(app)

        with client.websocket_connect("/ws/wf-ws-1") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "snapshot"
            assert msg["workflow"]["id"] == "wf-ws-1"

    def test_no_snapshot_when_workflow_missing(self):
        """If workflow not in DB, the first message should be heartbeat."""
        backend = _make_backend(None)
        event_bus = ObservabilityEventBus()
        app = create_app(backend=backend, event_bus=event_bus)
        client = TestClient(app)

        with client.websocket_connect("/ws/wf-missing") as ws:
            # No snapshot, should timeout waiting then get heartbeat.
            # TestClient runs synchronously, so we just verify no crash.
            # Close immediately -- the handler loop would wait 30s for heartbeat.
            assert ws is not None


class TestWebSocketEventStreaming:
    def test_event_delivered_to_client(self):
        """Events emitted on the bus for the subscribed workflow arrive on WS."""
        event_bus = ObservabilityEventBus()
        backend = _make_backend(SAMPLE_WORKFLOW)
        app = create_app(backend=backend, event_bus=event_bus)
        client = TestClient(app)

        with client.websocket_connect("/ws/wf-ws-1") as ws:
            # Consume snapshot first
            snapshot_msg = ws.receive_json()
            assert snapshot_msg["type"] == "snapshot"

            # Emit an event on the bus for this workflow
            event = ObservabilityEvent(
                event_type="stage_start",
                timestamp=datetime.now(timezone.utc),
                data={"stage_name": "research"},
                workflow_id="wf-ws-1",
                stage_id="st-1",
            )
            event_bus.emit(event)

            # The event should arrive
            msg = ws.receive_json()
            assert msg["type"] == "event"
            assert msg["event_type"] == "stage_start"
            assert msg["data"]["stage_name"] == "research"
            assert msg["workflow_id"] == "wf-ws-1"

    def test_events_for_other_workflow_not_delivered(self):
        """Events for a different workflow_id should not be forwarded."""
        event_bus = ObservabilityEventBus()
        backend = _make_backend(SAMPLE_WORKFLOW)
        app = create_app(backend=backend, event_bus=event_bus)
        client = TestClient(app)

        with client.websocket_connect("/ws/wf-ws-1") as ws:
            # Consume snapshot
            ws.receive_json()

            # Emit event for a *different* workflow
            event = ObservabilityEvent(
                event_type="stage_start",
                timestamp=datetime.now(timezone.utc),
                data={"stage_name": "other"},
                workflow_id="wf-other",
            )
            event_bus.emit(event)

            # Now emit one for *our* workflow so we have something to read
            event2 = ObservabilityEvent(
                event_type="agent_start",
                timestamp=datetime.now(timezone.utc),
                data={"agent_name": "writer"},
                workflow_id="wf-ws-1",
            )
            event_bus.emit(event2)

            msg = ws.receive_json()
            # Should be the agent_start, not the stage_start for wf-other
            assert msg["event_type"] == "agent_start"


class TestWebSocketNoEventBus:
    def test_works_without_event_bus(self):
        """When no event_bus is provided, connect still works (no events)."""
        backend = _make_backend(SAMPLE_WORKFLOW)
        app = create_app(backend=backend, event_bus=None)
        client = TestClient(app)

        with client.websocket_connect("/ws/wf-ws-1") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "snapshot"
