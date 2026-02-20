"""Tests for events/event_bus.py (TemperEventBus)."""

import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from temper_ai.events.event_bus import TemperEventBus
from temper_ai.events.models import EventLog, EventSubscription  # noqa: F401 — table registration
from temper_ai.events.constants import EVENT_WORKFLOW_COMPLETED, EVENT_STAGE_COMPLETED


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    SQLModel.metadata.drop_all(eng)


@pytest.fixture
def session_factory(engine):
    @contextmanager
    def _factory():
        with Session(engine, expire_on_commit=False) as session:
            yield session
            session.commit()

    return _factory


@pytest.fixture
def mock_obs_bus():
    return MagicMock()


@pytest.fixture
def bus(session_factory, mock_obs_bus):
    return TemperEventBus(
        observability_bus=mock_obs_bus,
        session_factory=session_factory,
        persist=True,
    )


@pytest.fixture
def bus_no_db(mock_obs_bus):
    return TemperEventBus(
        observability_bus=mock_obs_bus,
        session_factory=None,
        persist=False,
    )


class TestTemperEventBusInit:
    def test_default_obs_bus_created(self):
        bus = TemperEventBus()
        assert bus._obs_bus is not None

    def test_custom_obs_bus(self, mock_obs_bus):
        bus = TemperEventBus(observability_bus=mock_obs_bus)
        assert bus._obs_bus is mock_obs_bus

    def test_persist_default(self):
        bus = TemperEventBus()
        assert bus._persist is True


class TestEmit:
    def test_emit_forwards_to_obs_bus(self, bus, mock_obs_bus):
        bus.emit(EVENT_WORKFLOW_COMPLETED, payload={"run": "1"})
        assert mock_obs_bus.emit.called

    def test_emit_persists_to_db(self, bus, session_factory):
        bus.emit(EVENT_WORKFLOW_COMPLETED, source_workflow_id="wf-1")
        with session_factory() as session:
            records = session.exec(select(EventLog)).all()
        assert len(records) == 1
        assert records[0].event_type == EVENT_WORKFLOW_COMPLETED

    def test_emit_no_db_still_forwards(self, bus_no_db, mock_obs_bus):
        bus_no_db.emit(EVENT_STAGE_COMPLETED)
        assert mock_obs_bus.emit.called

    def test_emit_with_all_params(self, bus, session_factory):
        bus.emit(
            event_type="agent.completed",
            payload={"output": "done"},
            source_workflow_id="wf-x",
            source_stage_name="stage-1",
            agent_id="agent-1",
        )
        with session_factory() as session:
            record = session.exec(select(EventLog)).first()
        assert record.source_stage_name == "stage-1"
        assert record.agent_id == "agent-1"
        assert record.payload == {"output": "done"}

    def test_emit_db_failure_does_not_crash(self, mock_obs_bus):
        def bad_factory():
            raise RuntimeError("DB down")

        bus = TemperEventBus(
            observability_bus=mock_obs_bus,
            session_factory=bad_factory,
            persist=True,
        )
        # Should not raise; just logs warning
        bus.emit("workflow.completed")
        assert mock_obs_bus.emit.called


class TestSubscribePersistent:
    def test_subscribe_returns_id(self, bus):
        sub_id = bus.subscribe_persistent(
            agent_id="agent-1",
            event_type=EVENT_WORKFLOW_COMPLETED,
        )
        assert isinstance(sub_id, str)
        assert len(sub_id) > 0

    def test_subscribe_with_handler_ref(self, bus):
        sub_id = bus.subscribe_persistent(
            agent_id="agent-1",
            event_type="stage.failed",
            handler_ref="mymod.handler",
        )
        sub = bus._registry.get_by_id(sub_id)
        assert sub is not None
        assert sub.handler_ref == "mymod.handler"

    def test_subscribe_with_workflow_trigger(self, bus):
        sub_id = bus.subscribe_persistent(
            agent_id=None,
            event_type=EVENT_WORKFLOW_COMPLETED,
            workflow_to_trigger="path/wf.yaml",
        )
        sub = bus._registry.get_by_id(sub_id)
        assert sub.workflow_to_trigger == "path/wf.yaml"


class TestWaitForEvent:
    def test_wait_receives_event(self, bus):
        received = []

        def emitter():
            time.sleep(0.05)  # intentional delay before emitting
            bus.emit(EVENT_WORKFLOW_COMPLETED, payload={"x": 1})

        t = threading.Thread(target=emitter, daemon=True)
        t.start()

        result = bus.wait_for_event(EVENT_WORKFLOW_COMPLETED, timeout_seconds=2)
        t.join(timeout=1)
        assert result == {"x": 1}

    def test_wait_timeout_returns_none(self, bus):
        result = bus.wait_for_event("never.happens", timeout_seconds=0)
        assert result is None

    def test_wait_with_source_filter(self, bus):
        received = []

        def emitter():
            time.sleep(0.05)  # intentional delay before emitting
            bus.emit(EVENT_WORKFLOW_COMPLETED, payload={"z": 2}, source_workflow_id="wf-1")

        t = threading.Thread(target=emitter, daemon=True)
        t.start()
        result = bus.wait_for_event(
            EVENT_WORKFLOW_COMPLETED,
            timeout_seconds=2,
            source_workflow_filter="wf-1",
        )
        t.join(timeout=1)
        assert result == {"z": 2}


class TestReplayEvents:
    def test_replay_all_events(self, bus, session_factory):
        bus.emit(EVENT_WORKFLOW_COMPLETED)
        bus.emit(EVENT_STAGE_COMPLETED)

        events = bus.replay_events()
        assert len(events) == 2

    def test_replay_filter_by_type(self, bus):
        bus.emit(EVENT_WORKFLOW_COMPLETED)
        bus.emit(EVENT_STAGE_COMPLETED)

        events = bus.replay_events(event_type=EVENT_WORKFLOW_COMPLETED)
        assert all(e.event_type == EVENT_WORKFLOW_COMPLETED for e in events)

    def test_replay_filter_by_since(self, bus):
        before = datetime.now(timezone.utc)
        bus.emit(EVENT_WORKFLOW_COMPLETED)

        events = bus.replay_events(since=before)
        assert len(events) >= 1

    def test_replay_limit(self, bus):
        for _ in range(5):
            bus.emit(EVENT_WORKFLOW_COMPLETED)

        events = bus.replay_events(limit=2)
        assert len(events) <= 2

    def test_replay_no_session_returns_empty(self, bus_no_db):
        events = bus_no_db.replay_events()
        assert events == []


class TestDispatchSubscriptions:
    def test_handler_called_on_emit(self, bus, session_factory):
        handler_calls = []

        def my_handler(event_type, payload):
            handler_calls.append((event_type, payload))

        with patch(
            "temper_ai.events.event_bus.resolve_handler",
            return_value=my_handler,
        ):
            bus.subscribe_persistent(
                agent_id="a",
                event_type=EVENT_WORKFLOW_COMPLETED,
                handler_ref="mymod.my_handler",
            )
            bus.emit(EVENT_WORKFLOW_COMPLETED, payload={"k": "v"})

        assert len(handler_calls) >= 1

    def test_workflow_triggered_on_emit(self, bus, session_factory):
        with patch.object(bus._trigger, "trigger") as mock_trigger:
            bus.subscribe_persistent(
                agent_id="a",
                event_type=EVENT_WORKFLOW_COMPLETED,
                workflow_to_trigger="path/wf.yaml",
            )
            bus.emit(EVENT_WORKFLOW_COMPLETED)
            mock_trigger.assert_called_once()
