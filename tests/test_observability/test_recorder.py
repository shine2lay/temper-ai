"""Tests for temper_ai/observability/recorder.py — DB-backed event persistence.

The conftest.py autouse fixture initialises an in-memory SQLite database
before each test, so all DB writes land in a clean ephemeral store.

Covers:
- record() creates events in the DB and returns the event ID
- record() with an explicit event_id
- get_events() with no filters returns all events
- get_events() filtered by execution_id
- get_events() filtered by event_type
- get_events() filtered by parent_id
- get_events() filtered by status
- get_events() limit is respected
- update_event() changes status on an existing event
- update_event() merges data into an existing event
- update_event() on unknown event_id does not crash
- Event data serialization round-trip
- copy_events_for_fork() remaps IDs into a new execution
"""

import uuid

from temper_ai.observability.event_types import EventType
from temper_ai.observability.recorder import (
    copy_events_for_fork,
    get_events,
    record,
    update_event,
)

# ---------------------------------------------------------------------------
# record()
# ---------------------------------------------------------------------------

class TestRecord:
    def test_returns_event_id(self):
        eid = record(EventType.WORKFLOW_STARTED, execution_id="exec-r1")
        assert isinstance(eid, str)
        assert len(eid) > 0

    def test_returns_custom_event_id(self):
        custom_id = "my-custom-event-id"
        eid = record(EventType.STAGE_STARTED, event_id=custom_id, execution_id="exec-r2")
        assert eid == custom_id

    def test_event_persisted_to_db(self):
        eid = record(
            EventType.AGENT_STARTED,
            data={"agent": "planner"},
            execution_id="exec-r3",
        )
        events = get_events(execution_id="exec-r3")
        assert len(events) == 1
        assert events[0]["id"] == eid
        assert events[0]["type"] == EventType.AGENT_STARTED

    def test_event_with_parent_id(self):
        parent_id = str(uuid.uuid4())
        record(
            EventType.LLM_CALL_STARTED,
            parent_id=parent_id,
            execution_id="exec-r4",
        )
        events = get_events(execution_id="exec-r4")
        assert events[0]["parent_id"] == parent_id

    def test_event_with_status(self):
        record(
            EventType.STAGE_STARTED,
            status="running",
            execution_id="exec-r5",
        )
        events = get_events(execution_id="exec-r5")
        assert events[0]["status"] == "running"

    def test_event_with_empty_data(self):
        """Passing no data should default to empty dict."""
        record(EventType.WORKFLOW_COMPLETED, execution_id="exec-r6")
        events = get_events(execution_id="exec-r6")
        assert events[0]["data"] == {}

    def test_event_data_serialisation(self):
        """Arbitrary JSON payload should survive a DB round-trip."""
        payload = {
            "nested": {"key": "value"},
            "list": [1, 2, 3],
            "number": 42,
            "flag": True,
            "null_val": None,
        }
        record(
            EventType.AGENT_COMPLETED,
            data=payload,
            execution_id="exec-r7",
        )
        events = get_events(execution_id="exec-r7")
        assert events[0]["data"] == payload

    def test_multiple_events_same_execution(self):
        for event_type in [
            EventType.WORKFLOW_STARTED,
            EventType.STAGE_STARTED,
            EventType.AGENT_STARTED,
        ]:
            record(event_type, execution_id="exec-r8")

        events = get_events(execution_id="exec-r8")
        assert len(events) == 3


# ---------------------------------------------------------------------------
# get_events()
# ---------------------------------------------------------------------------

class TestGetEvents:
    def _seed(self, execution_id: str, n: int = 3):
        """Seed n events for a given execution_id."""
        ids = []
        for i in range(n):
            eid = record(
                EventType.STAGE_STARTED,
                data={"index": i},
                execution_id=execution_id,
            )
            ids.append(eid)
        return ids

    def test_no_filters_returns_all(self):
        """With no filters every event in the DB is returned (up to limit)."""
        self._seed("exec-g1", n=3)
        self._seed("exec-g2", n=2)
        events = get_events()
        # At least 5 events from this test (other tests in session are isolated by DB reset)
        assert len(events) >= 5

    def test_filter_by_execution_id(self):
        self._seed("exec-g3", n=4)
        self._seed("exec-g4", n=2)
        events = get_events(execution_id="exec-g3")
        assert len(events) == 4
        assert all(e["execution_id"] == "exec-g3" for e in events)

    def test_filter_by_event_type(self):
        record(EventType.WORKFLOW_STARTED, execution_id="exec-g5")
        record(EventType.AGENT_STARTED, execution_id="exec-g5")
        record(EventType.AGENT_STARTED, execution_id="exec-g5")

        events = get_events(execution_id="exec-g5", event_type=EventType.AGENT_STARTED)
        assert len(events) == 2
        assert all(e["type"] == EventType.AGENT_STARTED for e in events)

    def test_filter_by_parent_id(self):
        parent_eid = record(EventType.STAGE_STARTED, execution_id="exec-g6")
        record(EventType.AGENT_STARTED, parent_id=parent_eid, execution_id="exec-g6")
        record(EventType.AGENT_STARTED, parent_id=parent_eid, execution_id="exec-g6")
        record(EventType.WORKFLOW_STARTED, execution_id="exec-g6")  # no parent

        events = get_events(execution_id="exec-g6", parent_id=parent_eid)
        assert len(events) == 2
        assert all(e["parent_id"] == parent_eid for e in events)

    def test_filter_by_status(self):
        record(EventType.STAGE_STARTED, status="running", execution_id="exec-g7")
        record(EventType.STAGE_COMPLETED, status="completed", execution_id="exec-g7")
        record(EventType.STAGE_FAILED, status="failed", execution_id="exec-g7")

        running = get_events(execution_id="exec-g7", status="running")
        assert len(running) == 1
        assert running[0]["status"] == "running"

    def test_limit_is_respected(self):
        self._seed("exec-g8", n=10)
        events = get_events(execution_id="exec-g8", limit=3)
        assert len(events) == 3

    def test_results_contain_expected_fields(self):
        record(
            EventType.LLM_CALL_STARTED,
            data={"model": "qwen"},
            execution_id="exec-g9",
            status="running",
        )
        events = get_events(execution_id="exec-g9")
        assert len(events) == 1
        e = events[0]
        assert "id" in e
        assert "type" in e
        assert "parent_id" in e
        assert "execution_id" in e
        assert "status" in e
        assert "data" in e
        assert "timestamp" in e
        # Timestamp is an ISO 8601 string
        assert isinstance(e["timestamp"], str)
        assert "T" in e["timestamp"]

    def test_no_results_returns_empty_list(self):
        events = get_events(execution_id="exec-nonexistent-xyz")
        assert events == []


# ---------------------------------------------------------------------------
# update_event()
# ---------------------------------------------------------------------------

class TestUpdateEvent:
    def test_update_status(self):
        eid = record(EventType.STAGE_STARTED, status="running", execution_id="exec-u1")
        update_event(eid, status="completed")
        events = get_events(execution_id="exec-u1")
        assert events[0]["status"] == "completed"

    def test_update_data_merges(self):
        eid = record(
            EventType.AGENT_STARTED,
            data={"input": "hello"},
            execution_id="exec-u2",
        )
        update_event(eid, data={"output": "world"})
        events = get_events(execution_id="exec-u2")
        d = events[0]["data"]
        assert d["input"] == "hello"
        assert d["output"] == "world"

    def test_update_data_overwrites_existing_key(self):
        eid = record(
            EventType.AGENT_STARTED,
            data={"status_detail": "initialising"},
            execution_id="exec-u3",
        )
        update_event(eid, data={"status_detail": "done"})
        events = get_events(execution_id="exec-u3")
        assert events[0]["data"]["status_detail"] == "done"

    def test_update_status_and_data_together(self):
        eid = record(EventType.LLM_CALL_STARTED, status="running", execution_id="exec-u4")
        update_event(eid, status="completed", data={"tokens": 123})
        events = get_events(execution_id="exec-u4")
        e = events[0]
        assert e["status"] == "completed"
        assert e["data"]["tokens"] == 123

    def test_update_unknown_event_does_not_crash(self):
        """Updating a non-existent event should log a warning but not raise."""
        update_event("event-does-not-exist", status="completed")  # no crash

    def test_update_no_fields_is_noop(self):
        """Calling update_event with no changes should not fail."""
        eid = record(EventType.STAGE_STARTED, status="running", execution_id="exec-u5")
        update_event(eid)  # Neither status nor data — no crash
        events = get_events(execution_id="exec-u5")
        assert events[0]["status"] == "running"


# ---------------------------------------------------------------------------
# copy_events_for_fork()
# ---------------------------------------------------------------------------

class TestCopyEventsForFork:
    def _build_execution(self, execution_id: str, stage_name: str) -> dict:
        """Create a minimal workflow + stage + agent event tree."""
        wf_id = record(
            EventType.WORKFLOW_STARTED,
            execution_id=execution_id,
            status="completed",
        )
        stage_id = record(
            EventType.STAGE_STARTED,
            parent_id=wf_id,
            execution_id=execution_id,
            data={"name": stage_name},
            status="completed",
        )
        agent_id = record(
            EventType.AGENT_STARTED,
            parent_id=stage_id,
            execution_id=execution_id,
            data={"agent": "planner"},
            status="completed",
        )
        return {"wf_id": wf_id, "stage_id": stage_id, "agent_id": agent_id}

    def test_copy_returns_new_workflow_event_id(self):
        src = "exec-fork-src-1"
        dst = "exec-fork-dst-1"
        ids = self._build_execution(src, "build")

        new_wf_id = copy_events_for_fork(src, dst, {"build"})
        assert new_wf_id is not None
        assert new_wf_id != ids["wf_id"]

    def test_copied_events_have_new_execution_id(self):
        src = "exec-fork-src-2"
        dst = "exec-fork-dst-2"
        self._build_execution(src, "test")

        copy_events_for_fork(src, dst, {"test"})

        dst_events = get_events(execution_id=dst)
        assert len(dst_events) > 0
        assert all(e["execution_id"] == dst for e in dst_events)

    def test_only_requested_nodes_are_copied(self):
        src = "exec-fork-src-3"
        dst = "exec-fork-dst-3"

        wf_id = record(EventType.WORKFLOW_STARTED, execution_id=src)
        record(
            EventType.STAGE_STARTED,
            parent_id=wf_id,
            execution_id=src,
            data={"name": "stage_a"},
        )
        record(
            EventType.STAGE_STARTED,
            parent_id=wf_id,
            execution_id=src,
            data={"name": "stage_b"},
        )

        copy_events_for_fork(src, dst, {"stage_a"})  # Only copy stage_a

        dst_events = get_events(execution_id=dst)
        {e["type"] for e in dst_events}
        dst_data = [e["data"] for e in dst_events]

        # stage_a events should be present, stage_b events should not
        stage_names = {d.get("name") for d in dst_data}
        assert "stage_a" in stage_names
        assert "stage_b" not in stage_names

    def test_missing_source_execution_returns_none(self):
        result = copy_events_for_fork("exec-nonexistent-src", "exec-dst-x", {"stage"})
        assert result is None

    def test_fork_marks_restored_events(self):
        """Copied events (not the workflow event) should carry restored_from_fork=True."""
        src = "exec-fork-src-4"
        dst = "exec-fork-dst-4"
        self._build_execution(src, "review")

        copy_events_for_fork(src, dst, {"review"})

        dst_events = get_events(execution_id=dst)
        # Skip the workflow.started event; all others should be marked
        non_workflow = [e for e in dst_events if e["type"] != "workflow.started"]
        for e in non_workflow:
            assert e["data"].get("restored_from_fork") is True
            assert e["data"].get("source_execution_id") == src
