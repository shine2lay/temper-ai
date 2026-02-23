"""End-to-end integration tests for the TemperEventBus event flow."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from temper_ai.events.constants import (
    EVENT_STAGE_COMPLETED,
    EVENT_WORKFLOW_COMPLETED,
)
from temper_ai.events.event_bus import TemperEventBus
from temper_ai.events.models import (
    EventLog,
)  # noqa: F401 — table registration

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine():
    """In-memory SQLite engine with all M9 tables."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    SQLModel.metadata.drop_all(eng)


@pytest.fixture()
def session_factory(engine):
    """Session factory compatible with TemperEventBus."""

    @contextmanager
    def _factory() -> Generator[Session, None, None]:
        with Session(engine, expire_on_commit=False) as session:
            yield session
            session.commit()

    return _factory


@pytest.fixture()
def mock_obs_bus():
    return MagicMock()


@pytest.fixture()
def bus(session_factory, mock_obs_bus):
    return TemperEventBus(
        observability_bus=mock_obs_bus,
        session_factory=session_factory,
        persist=True,
    )


@pytest.fixture()
def bus_no_db(mock_obs_bus):
    return TemperEventBus(
        observability_bus=mock_obs_bus,
        session_factory=None,
        persist=False,
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _query_event_log(session_factory, event_type: str | None = None) -> list[EventLog]:
    """Query event_log rows from in-memory DB."""
    with session_factory() as session:
        stmt = select(EventLog)
        if event_type:
            stmt = stmt.where(EventLog.event_type == event_type)
        return session.exec(stmt).all()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmitPersistsEvent:
    """Emitting an event stores it in the event_log table."""

    def test_emit_event_persisted_in_db(self, bus, session_factory) -> None:
        bus.emit(
            event_type=EVENT_WORKFLOW_COMPLETED,
            payload={"workflow_id": "wf-001"},
            source_workflow_id="wf-001",
        )

        rows = _query_event_log(session_factory, event_type=EVENT_WORKFLOW_COMPLETED)
        assert len(rows) == 1
        assert rows[0].source_workflow_id == "wf-001"
        assert rows[0].payload == {"workflow_id": "wf-001"}

    def test_emit_multiple_events_all_persisted(self, bus, session_factory) -> None:
        bus.emit(EVENT_WORKFLOW_COMPLETED, payload={"x": 1}, source_workflow_id="wf-a")
        bus.emit(EVENT_STAGE_COMPLETED, payload={"x": 2}, source_workflow_id="wf-a")

        all_rows = _query_event_log(session_factory)
        assert len(all_rows) == 2


class TestSubscriptionMatching:
    """Subscriptions are evaluated when an event is emitted."""

    def test_matching_subscription_triggers_callback(self, bus) -> None:
        received: list[Any] = []

        def _handler(event_type: str, payload: dict[str, Any] | None) -> None:
            received.append((event_type, payload))

        # resolve_handler is imported at module level in event_bus, patch there
        with patch(
            "temper_ai.events.event_bus.resolve_handler",
            return_value=_handler,
        ):
            bus.subscribe_persistent(
                agent_id="agent-1",
                event_type=EVENT_WORKFLOW_COMPLETED,
                handler_ref="some.module.handler",
            )
            bus.emit(EVENT_WORKFLOW_COMPLETED, payload={"val": 42})

        assert len(received) == 1
        assert received[0][1] == {"val": 42}

    def test_non_matching_event_type_does_not_trigger(self, bus) -> None:
        received: list[Any] = []

        def _handler(event_type: str, payload: dict[str, Any] | None) -> None:
            received.append(event_type)

        with patch(
            "temper_ai.events.event_bus.resolve_handler",
            return_value=_handler,
        ):
            bus.subscribe_persistent(
                agent_id="agent-2",
                event_type="custom.specific_event",
                handler_ref="some.module.handler",
            )
            bus.emit(EVENT_WORKFLOW_COMPLETED, payload={"val": 1})

        assert len(received) == 0


class TestPersistentSubscribeAndEmit:
    """subscribe_persistent followed by matching emit fires the callback."""

    def test_subscribe_then_emit_fires(self, bus) -> None:
        fired: list[str] = []

        def _handler(event_type: str, payload: dict[str, Any] | None) -> None:
            fired.append(event_type)

        # Patch where event_bus imports resolve_handler
        with patch(
            "temper_ai.events.event_bus.resolve_handler",
            return_value=_handler,
        ):
            sub_id = bus.subscribe_persistent(
                agent_id="agent-3",
                event_type="order.created",
                handler_ref="some.module.on_order",
            )
            assert sub_id  # subscription returned a valid ID
            bus.emit("order.created", payload={"order_id": "o-001"})

        assert "order.created" in fired

    def test_non_matching_subscribe_does_not_fire(self, bus) -> None:
        fired: list[str] = []

        def _handler(event_type: str, payload: dict[str, Any] | None) -> None:
            fired.append(event_type)

        with patch(
            "temper_ai.events.event_bus.resolve_handler",
            return_value=_handler,
        ):
            bus.subscribe_persistent(
                agent_id="agent-4",
                event_type="order.cancelled",
                handler_ref="some.module.on_cancel",
            )
            bus.emit("order.created", payload={"order_id": "o-002"})

        assert len(fired) == 0


class TestReplayEvents:
    """replay_events returns persisted events from DB."""

    def test_replay_returns_persisted_events(self, bus, session_factory) -> None:
        bus.emit(
            EVENT_WORKFLOW_COMPLETED, payload={"run": 1}, source_workflow_id="wf-r"
        )
        bus.emit(
            EVENT_WORKFLOW_COMPLETED, payload={"run": 2}, source_workflow_id="wf-r"
        )

        replayed = bus.replay_events(event_type=EVENT_WORKFLOW_COMPLETED)
        assert len(replayed) == 2

    def test_replay_filtered_by_event_type(self, bus, session_factory) -> None:
        bus.emit(EVENT_WORKFLOW_COMPLETED, payload={"x": 1})
        bus.emit(EVENT_STAGE_COMPLETED, payload={"x": 2})

        replayed = bus.replay_events(event_type=EVENT_STAGE_COMPLETED)
        assert len(replayed) == 1
        assert replayed[0].event_type == EVENT_STAGE_COMPLETED


class TestWorkflowCompletionEmit:
    """Workflow completion emits the workflow.completed event."""

    def test_workflow_completion_event_persisted(self, bus, session_factory) -> None:
        bus.emit(
            event_type=EVENT_WORKFLOW_COMPLETED,
            payload={"status": "completed", "workflow_name": "test_wf"},
            source_workflow_id="wf-comp-001",
        )

        rows = _query_event_log(session_factory, event_type=EVENT_WORKFLOW_COMPLETED)
        assert len(rows) == 1
        assert rows[0].payload["status"] == "completed"


class TestCrossWorkflowTrigger:
    """Cross-workflow triggers spawn a thread via CrossWorkflowTrigger."""

    def test_workflow_to_trigger_calls_cross_workflow_trigger(self, bus) -> None:
        with patch.object(bus._trigger, "trigger") as mock_trigger:
            bus.subscribe_persistent(
                agent_id=None,
                event_type="data.ready",
                workflow_to_trigger="downstream_workflow.yaml",
            )
            bus.emit("data.ready", payload={"table": "orders"})

        mock_trigger.assert_called_once_with(
            "downstream_workflow.yaml", inputs={"table": "orders"}
        )


class TestEventBusNoDB:
    """Memory-only mode: no session_factory → events still forwarded to obs_bus."""

    def test_memory_only_mode_emits_to_obs_bus(self, bus_no_db, mock_obs_bus) -> None:
        bus_no_db.emit(EVENT_WORKFLOW_COMPLETED, payload={"x": 1})

        mock_obs_bus.emit.assert_called_once()

    def test_memory_only_replay_returns_empty(self, bus_no_db) -> None:
        bus_no_db.emit(EVENT_WORKFLOW_COMPLETED, payload={"x": 1})
        result = bus_no_db.replay_events(event_type=EVENT_WORKFLOW_COMPLETED)
        assert result == []
