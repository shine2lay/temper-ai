"""Tests for temper_ai/events/_bus_helpers.py."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from temper_ai.events._bus_helpers import (
    convert_to_observability_event,
    evaluate_subscriptions,
    persist_event,
)


class TestPersistEvent:
    """Tests for persist_event."""

    def test_creates_event_record(self):
        session = MagicMock()
        with patch("temper_ai.events._bus_helpers.uuid.uuid4", return_value="evt-123"):
            event_id = persist_event(
                session=session,
                event_type="task.completed",
                payload={"result": "ok"},
                source_workflow_id="wf-1",
                source_stage_name="stage-1",
                agent_id="agent-1",
            )
        assert event_id == "evt-123"
        session.add.assert_called_once()

    def test_returns_string_id(self):
        session = MagicMock()
        event_id = persist_event(
            session=session,
            event_type="test",
            payload=None,
            source_workflow_id=None,
            source_stage_name=None,
            agent_id=None,
        )
        assert isinstance(event_id, str)
        assert len(event_id) > 0

    def test_handles_none_payload(self):
        session = MagicMock()
        event_id = persist_event(
            session=session,
            event_type="test",
            payload=None,
            source_workflow_id=None,
            source_stage_name=None,
            agent_id=None,
        )
        assert event_id is not None
        session.add.assert_called_once()


class TestEvaluateSubscriptions:
    """Tests for evaluate_subscriptions."""

    def test_returns_matching_subscriptions(self):
        sub1 = MagicMock()
        sub1.event_type = "task.completed"
        sub1.source_workflow_filter = None
        sub1.payload_filter = None
        sub1.active = True

        sub2 = MagicMock()
        sub2.event_type = "task.started"
        sub2.source_workflow_filter = None
        sub2.payload_filter = None
        sub2.active = True

        session = MagicMock()
        result_mock = MagicMock()
        result_mock.all.return_value = [sub1, sub2]
        session.exec.return_value = result_mock

        matches = evaluate_subscriptions(
            session=session,
            event_type="task.completed",
            payload=None,
            source_workflow_id=None,
        )
        assert sub1 in matches
        assert sub2 not in matches

    def test_empty_subscriptions(self):
        session = MagicMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        session.exec.return_value = result_mock

        matches = evaluate_subscriptions(
            session=session,
            event_type="task.completed",
            payload=None,
            source_workflow_id=None,
        )
        assert matches == []


class TestConvertToObservabilityEvent:
    """Tests for convert_to_observability_event."""

    def test_creates_event_with_payload(self):
        event = convert_to_observability_event(
            event_type="task.completed",
            payload={"status": "ok"},
            source_workflow_id="wf-1",
            agent_id="agent-1",
        )
        assert event.event_type == "task.completed"
        assert event.data == {"status": "ok"}
        assert event.workflow_id == "wf-1"
        assert event.agent_id == "agent-1"
        assert isinstance(event.timestamp, datetime)

    def test_none_payload_uses_empty_dict(self):
        event = convert_to_observability_event(
            event_type="test",
            payload=None,
            source_workflow_id=None,
            agent_id=None,
        )
        assert event.data == {}

    def test_none_workflow_and_agent(self):
        event = convert_to_observability_event(
            event_type="test",
            payload={"key": "val"},
            source_workflow_id=None,
            agent_id=None,
        )
        assert event.workflow_id is None
        assert event.agent_id is None
