"""Tests for events/models.py."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from temper_ai.events.models import EventLog, EventSubscription


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
def session(engine):
    with Session(engine) as s:
        yield s


class TestEventLog:
    def test_create_minimal(self, session):
        record = EventLog(
            id=str(uuid.uuid4()),
            event_type="workflow.completed",
        )
        session.add(record)
        session.commit()

        fetched = session.get(EventLog, record.id)
        assert fetched is not None
        assert fetched.event_type == "workflow.completed"
        assert fetched.consumed is False
        assert fetched.payload is None

    def test_create_with_payload(self, session):
        event_id = str(uuid.uuid4())
        record = EventLog(
            id=event_id,
            event_type="agent.completed",
            payload={"result": "ok"},
            source_workflow_id="wf-1",
        )
        session.add(record)
        session.commit()

        fetched = session.get(EventLog, event_id)
        assert fetched.payload == {"result": "ok"}
        assert fetched.source_workflow_id == "wf-1"

    def test_consumed_fields(self, session):
        now = datetime.now(timezone.utc)
        record = EventLog(
            id=str(uuid.uuid4()),
            event_type="stage.completed",
            consumed=True,
            consumed_at=now,
            consumed_by="agent-1",
        )
        session.add(record)
        session.commit()

        fetched = session.get(EventLog, record.id)
        assert fetched.consumed is True
        assert fetched.consumed_by == "agent-1"

    def test_timestamp_default(self, session):
        record = EventLog(id=str(uuid.uuid4()), event_type="custom")
        session.add(record)
        session.commit()

        fetched = session.get(EventLog, record.id)
        assert fetched.timestamp is not None


class TestEventSubscription:
    def test_create_minimal(self, session):
        sub = EventSubscription(
            id=str(uuid.uuid4()),
            event_type="workflow.completed",
        )
        session.add(sub)
        session.commit()

        fetched = session.get(EventSubscription, sub.id)
        assert fetched is not None
        assert fetched.active is True

    def test_create_full(self, session):
        sub_id = str(uuid.uuid4())
        sub = EventSubscription(
            id=sub_id,
            agent_id="agent-1",
            event_type="workflow.failed",
            source_workflow_filter="wf-1",
            payload_filter={"key": "val"},
            handler_ref="mymod.my_handler",
            workflow_to_trigger="path/to/wf.yaml",
        )
        session.add(sub)
        session.commit()

        fetched = session.get(EventSubscription, sub_id)
        assert fetched.agent_id == "agent-1"
        assert fetched.handler_ref == "mymod.my_handler"
        assert fetched.workflow_to_trigger == "path/to/wf.yaml"
        assert fetched.payload_filter == {"key": "val"}

    def test_deactivate(self, session):
        sub = EventSubscription(
            id=str(uuid.uuid4()),
            event_type="stage.started",
            active=True,
        )
        session.add(sub)
        session.commit()

        sub.active = False
        session.add(sub)
        session.commit()

        fetched = session.get(EventSubscription, sub.id)
        assert fetched.active is False
