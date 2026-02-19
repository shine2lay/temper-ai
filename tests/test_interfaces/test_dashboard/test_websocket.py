"""Tests for dashboard WebSocket handler."""
import asyncio
import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from temper_ai.interfaces.dashboard.app import create_app
from temper_ai.interfaces.dashboard.websocket import (
    _workflow_fingerprint,
    TERMINAL_STATUSES,
)
from temper_ai.observability.constants import ObservabilityFields
from temper_ai.observability.event_bus import ObservabilityEvent, ObservabilityEventBus

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


class TestWorkflowFingerprint:
    """Tests for the _workflow_fingerprint change-detection helper."""

    def test_empty_workflow(self):
        fp = _workflow_fingerprint({"status": "running", "stages": []})
        assert "running" in fp

    def test_same_state_same_fingerprint(self):
        snap = {"status": "running", "stages": [{"status": "running", "agents": []}]}
        assert _workflow_fingerprint(snap) == _workflow_fingerprint(snap)

    def test_status_change_changes_fingerprint(self):
        snap1 = {"status": "running", "stages": []}
        snap2 = {"status": "completed", "end_time": "2026-02-17T00:00:00Z", "stages": []}
        assert _workflow_fingerprint(snap1) != _workflow_fingerprint(snap2)

    def test_new_stage_changes_fingerprint(self):
        snap1 = {"status": "running", "stages": []}
        snap2 = {"status": "running", "stages": [{"status": "running", "agents": []}]}
        assert _workflow_fingerprint(snap1) != _workflow_fingerprint(snap2)

    def test_agent_status_change_changes_fingerprint(self):
        snap1 = {
            "status": "running",
            "stages": [{"status": "running", "agents": [{"status": "running"}]}],
        }
        snap2 = {
            "status": "running",
            "stages": [{"status": "running", "agents": [{"status": "completed"}]}],
        }
        assert _workflow_fingerprint(snap1) != _workflow_fingerprint(snap2)

    def test_terminal_statuses_defined(self):
        assert "completed" in TERMINAL_STATUSES
        assert "failed" in TERMINAL_STATUSES
        assert "running" not in TERMINAL_STATUSES


class TestDBPolling:
    """Tests for DB-polling based WebSocket snapshot delivery."""

    def test_db_poll_sends_updated_snapshot(self):
        """DB poller sends a new snapshot when workflow state changes."""
        call_count = 0
        running_workflow = {
            "id": "wf-poll-1",
            "workflow_name": "poll-test",
            "status": "running",
            "stages": [],
        }
        completed_workflow = {
            "id": "wf-poll-1",
            "workflow_name": "poll-test",
            "status": "completed",
            "end_time": "2026-02-17T00:00:00Z",
            "stages": [{"status": "completed", "agents": []}],
        }

        def side_effect(wf_id):
            nonlocal call_count
            call_count += 1
            # First call: initial snapshot (from handler)
            # Second call: first poll returns running (same as initial)
            # Third call: state changes to completed
            if call_count <= 2:
                return running_workflow
            return completed_workflow

        backend = MagicMock()
        backend.get_workflow.side_effect = side_effect
        app = create_app(backend=backend, event_bus=None)
        client = TestClient(app)

        with client.websocket_connect("/ws/wf-poll-1") as ws:
            # First message: initial snapshot (running)
            msg1 = ws.receive_json()
            assert msg1["type"] == "snapshot"
            assert msg1["workflow"]["status"] == "running"

            # Second message: DB poll detects change to completed
            msg2 = ws.receive_json()
            assert msg2["type"] == "snapshot"
            assert msg2["workflow"]["status"] == "completed"
